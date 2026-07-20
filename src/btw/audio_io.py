"""Local mic + speaker for aiortc — safe levels, resampled, ring-buffered."""
from __future__ import annotations

import asyncio
import fractions
import threading
import time
from pathlib import Path
from typing import Optional

import numpy as np

try:
    import sounddevice as sd
except ImportError:  # pragma: no cover
    sd = None  # type: ignore

from av import AudioFrame
from av.audio.resampler import AudioResampler
from aiortc import MediaStreamTrack
from aiortc.mediastreams import MediaStreamError

SAMPLE_RATE = 48000
FRAME_SAMPLES = 960  # 20 ms @ 48 kHz
RING_SECONDS = 3

# Hard safety: never let peaks hit full scale (ear protection)
SPEAKER_GAIN = 0.25
SPEAKER_PEAK_LIMIT = 0.35
# Don't play until this much is buffered (avoids startup crack / garbage)
SPEAKER_PREROLL = int(SAMPLE_RATE * 0.08)  # 80 ms


class _FloatRing:
    def __init__(self, capacity: int):
        self._buf = np.zeros(capacity, dtype=np.float32)
        self._cap = capacity
        self._r = 0
        self._w = 0
        self._size = 0
        self._lock = threading.Lock()

    def clear(self) -> None:
        with self._lock:
            self._r = self._w = self._size = 0

    def write(self, samples: np.ndarray) -> None:
        samples = np.asarray(samples, dtype=np.float32).reshape(-1)
        if samples.size == 0:
            return
        with self._lock:
            free = self._cap - self._size
            if samples.size > free:
                drop = samples.size - free
                self._r = (self._r + drop) % self._cap
                self._size -= drop
            n = samples.size
            end = self._w + n
            if end <= self._cap:
                self._buf[self._w : end] = samples
            else:
                first = self._cap - self._w
                self._buf[self._w :] = samples[:first]
                self._buf[: n - first] = samples[first:]
            self._w = (self._w + n) % self._cap
            self._size = min(self._cap, self._size + n)

    def read(self, n: int) -> np.ndarray:
        out = np.zeros(n, dtype=np.float32)
        with self._lock:
            take = min(n, self._size)
            if take <= 0:
                return out
            end = self._r + take
            if end <= self._cap:
                out[:take] = self._buf[self._r : end]
            else:
                first = self._cap - self._r
                out[:first] = self._buf[self._r :]
                out[first:take] = self._buf[: take - first]
            self._r = (self._r + take) % self._cap
            self._size -= take
        return out

    @property
    def size(self) -> int:
        with self._lock:
            return self._size


def _to_mono_float(arr: np.ndarray) -> np.ndarray:
    a = np.asarray(arr)
    if a.size == 0:
        return np.zeros(0, dtype=np.float32)
    if a.ndim == 1:
        mono = a
    elif a.shape[0] <= 8 and a.shape[0] < a.shape[-1]:
        mono = a.mean(axis=0)
    else:
        mono = a.mean(axis=-1)
    mono = np.asarray(mono, dtype=np.float64).reshape(-1)
    # int paths
    if arr.dtype == np.int16:
        mono = mono / 32768.0
    elif arr.dtype == np.int32:
        mono = mono / 2147483648.0
    elif arr.dtype == np.uint8:
        mono = (mono - 128.0) / 128.0
    # already float: assume [-1,1]; if clearly not, scale down
    peak = float(np.max(np.abs(mono))) if mono.size else 0.0
    if peak > 8.0:
        # likely wrong dtype interpretation — kill it
        return np.zeros(mono.size, dtype=np.float32)
    if peak > 1.5:
        mono = mono / peak
    return mono.astype(np.float32)


def _limit(mono: np.ndarray, gain: float = SPEAKER_GAIN, peak: float = SPEAKER_PEAK_LIMIT) -> np.ndarray:
    x = mono * gain
    # soft tanh-ish limit then hard clip
    x = np.tanh(x * 1.2) / np.tanh(1.2)
    return np.clip(x, -peak, peak).astype(np.float32)


class MicrophoneTrack(MediaStreamTrack):
    kind = "audio"

    def __init__(self, device: Optional[int | str] = None):
        super().__init__()
        if sd is None:
            raise RuntimeError("sounddevice not installed")
        self._ring = _FloatRing(SAMPLE_RATE * RING_SECONDS)
        self._pts = 0
        self._stream = None
        self._started = time.monotonic()
        self._pending = np.zeros(0, dtype=np.float32)
        self._in_rate = SAMPLE_RATE
        self.muted = False

        def callback(indata, frames, time_info, status):  # noqa: ARG001
            if self.muted:
                return
            mono = indata
            if mono.ndim > 1:
                mono = mono.mean(axis=1)
            self._ring.write(np.asarray(mono, dtype=np.float32))

        try:
            info = (
                sd.query_devices(device, "input")
                if device is not None
                else sd.query_devices(kind="input")
            )
            def_rate = int(info.get("default_samplerate") or SAMPLE_RATE)
            if def_rate in (44100, 48000, 32000, 16000, 24000):
                self._in_rate = def_rate
        except Exception:
            pass

        self._stream = sd.InputStream(
            samplerate=self._in_rate,
            channels=1,
            dtype="float32",
            blocksize=0,
            device=device,
            latency="high",
            callback=callback,
        )
        self._stream.start()

    def resync_clock(self) -> None:
        """Reset pacing after a long inject so we don't dump/starve frames."""
        self._started = time.monotonic()
        self._pts = 0
        self._pending = np.zeros(0, dtype=np.float32)
        # drop stale buffered audio; take live from now
        self._ring = _FloatRing(SAMPLE_RATE * RING_SECONDS)

    def _resample_to_48k(self, mono: np.ndarray, src_rate: int) -> np.ndarray:
        if src_rate == SAMPLE_RATE or mono.size == 0:
            return mono
        duration = mono.size / float(src_rate)
        n_out = int(round(duration * SAMPLE_RATE))
        if n_out <= 0:
            return np.zeros(0, dtype=np.float32)
        x_old = np.linspace(0.0, 1.0, num=mono.size, endpoint=False)
        x_new = np.linspace(0.0, 1.0, num=n_out, endpoint=False)
        return np.interp(x_new, x_old, mono).astype(np.float32)

    async def recv(self) -> AudioFrame:
        if self.readyState != "live":
            raise MediaStreamError

        need_in = (
            FRAME_SAMPLES
            if self._in_rate == SAMPLE_RATE
            else int(round(FRAME_SAMPLES * self._in_rate / SAMPLE_RATE))
        )

        target = self._started + (self._pts / SAMPLE_RATE)
        delay = target - time.monotonic()
        if delay > 0.001:
            await asyncio.sleep(delay)

        chunks = [self._pending]
        got = int(self._pending.size)
        tries = 0
        while got < need_in and tries < 40:
            chunk = self._ring.read(need_in - got)
            chunks.append(chunk)
            got += chunk.size
            if got < need_in:
                await asyncio.sleep(0.004)
            tries += 1

        raw = np.concatenate(chunks) if chunks else np.zeros(0, dtype=np.float32)
        if raw.size < need_in:
            raw = np.pad(raw, (0, need_in - raw.size))
        self._pending = raw[need_in:] if raw.size > need_in else np.zeros(0, dtype=np.float32)
        if self.muted:
            samples = np.zeros(FRAME_SAMPLES, dtype=np.float32)
        else:
            samples = self._resample_to_48k(raw[:need_in], self._in_rate)
            if samples.size < FRAME_SAMPLES:
                samples = np.pad(samples, (0, FRAME_SAMPLES - samples.size))
            else:
                samples = samples[:FRAME_SAMPLES]
            samples = np.clip(samples * 0.9, -1.0, 1.0)

        pcm = (samples * 32767.0).astype(np.int16)
        frame = AudioFrame(format="s16", layout="mono", samples=FRAME_SAMPLES)
        frame.sample_rate = SAMPLE_RATE
        frame.planes[0].update(pcm.tobytes())
        frame.pts = self._pts
        frame.time_base = fractions.Fraction(1, SAMPLE_RATE)
        self._pts += FRAME_SAMPLES
        return frame

    def set_muted(self, muted: bool) -> None:
        self.muted = bool(muted)
        if self.muted:
            self._ring = _FloatRing(SAMPLE_RATE * RING_SECONDS)
            self._pending = np.zeros(0, dtype=np.float32)

    def stop(self) -> None:
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        super().stop()


class SpeakerPlayer:
    def __init__(self, device: Optional[int | str] = None, gain: float = SPEAKER_GAIN):
        if sd is None:
            raise RuntimeError("sounddevice not installed")
        self._device = device
        self._gain = float(gain)
        self._ring = _FloatRing(SAMPLE_RATE * RING_SECONDS)
        self._stream = None
        self._resampler = AudioResampler(format="s16", layout="mono", rate=SAMPLE_RATE)
        self._ready = False
        self._out_channels = 2
        self._frames_in = 0
        self.last_peak = 0.0  # pre-gain mono peak for visualizer

    def start(self) -> None:
        try:
            info = (
                sd.query_devices(self._device, "output")
                if self._device is not None
                else sd.query_devices(kind="output")
            )
            max_out = int(info.get("max_output_channels") or 2)
            self._out_channels = 2 if max_out >= 2 else 1
        except Exception:
            self._out_channels = 2

        ch = self._out_channels
        player = self

        def callback(outdata, frames, time_info, status):  # noqa: ARG001
            if not player._ready or player._ring.size < SPEAKER_PREROLL // 4:
                # preroll / not ready → silence (no noise)
                outdata.fill(0)
                if player._ring.size >= SPEAKER_PREROLL:
                    player._ready = True
                return
            mono = player._ring.read(frames)
            mono = _limit(mono, gain=1.0, peak=SPEAKER_PEAK_LIMIT)  # already gained on write
            if ch == 1:
                outdata[:, 0] = mono
            else:
                outdata[:, 0] = mono
                outdata[:, 1] = mono
                if outdata.shape[1] > 2:
                    outdata[:, 2:] = 0.0

        self._stream = sd.OutputStream(
            samplerate=SAMPLE_RATE,
            channels=ch,
            dtype="float32",
            blocksize=FRAME_SAMPLES,
            device=self._device,
            latency="high",
            callback=callback,
        )
        self._stream.start()

    async def push_frame(self, frame: AudioFrame) -> None:
        try:
            out_frames = self._resampler.resample(frame)
        except Exception:
            out_frames = [frame]

        for fr in out_frames:
            try:
                arr = fr.to_ndarray()
            except Exception:
                try:
                    raw = bytes(fr.planes[0])
                    arr = np.frombuffer(raw, dtype=np.int16)
                except Exception:
                    continue
            mono = _to_mono_float(arr)
            if mono.size == 0:
                continue
            # skip near-digital-full-scale garbage bursts (decode glitches)
            peak = float(np.max(np.abs(mono)))
            if peak > 0.99 and self._frames_in < 5:
                continue
            # Hold peak briefly so the GUI bar doesn't drop between packets
            self.last_peak = max(peak, float(self.last_peak) * 0.82)
            mono = _limit(mono, gain=self._gain, peak=SPEAKER_PEAK_LIMIT)
            self._ring.write(mono)
            self._frames_in += 1
            if not self._ready and self._ring.size >= SPEAKER_PREROLL:
                self._ready = True

    def stop(self) -> None:
        self._ready = False
        self.last_peak = 0.0
        self._ring.clear()
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None


class SilentTrack(MediaStreamTrack):
    kind = "audio"

    def __init__(self):
        super().__init__()
        self._pts = 0
        self._start = time.monotonic()

    async def recv(self) -> AudioFrame:
        if self.readyState != "live":
            raise MediaStreamError
        target = self._start + (self._pts / SAMPLE_RATE)
        delay = target - time.monotonic()
        if delay > 0.001:
            await asyncio.sleep(delay)
        samples = np.zeros(FRAME_SAMPLES, dtype=np.int16)
        frame = AudioFrame(format="s16", layout="mono", samples=FRAME_SAMPLES)
        frame.sample_rate = SAMPLE_RATE
        frame.planes[0].update(samples.tobytes())
        frame.pts = self._pts
        frame.time_base = fractions.Fraction(1, SAMPLE_RATE)
        self._pts += FRAME_SAMPLES
        return frame


def synthesize_speech_wav(text: str, path: str | Path, *, rate: int = 0) -> Path:
    """Windows SAPI TTS → wav file (System.Speech)."""
    import subprocess

    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    safe = (text or "").replace("'", "''")[:2500]
    out_ps = str(out).replace("'", "''")
    ps = (
        "Add-Type -AssemblyName System.Speech; "
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        f"$s.Rate = {int(rate)}; "
        f"$s.SetOutputToWaveFile('{out_ps}'); "
        f"$s.Speak('{safe}'); "
        "$s.Dispose();"
    )
    r = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if r.returncode != 0 or not out.is_file() or out.stat().st_size < 100:
        raise RuntimeError(
            f"SAPI TTS failed rc={r.returncode} stderr={(r.stderr or '')[:300]}"
        )
    return out


def _load_wav_mono_48k(wav_path: str | Path) -> np.ndarray:
    import wave

    path = Path(wav_path)
    with wave.open(str(path), "rb") as w:
        ch = w.getnchannels()
        sw = w.getsampwidth()
        rate = w.getframerate()
        raw = w.readframes(w.getnframes())
    if sw != 2:
        raise ValueError(f"need 16-bit wav, got sampwidth={sw}")
    pcm = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if ch > 1:
        pcm = pcm.reshape(-1, ch).mean(axis=1)
    if rate != SAMPLE_RATE and pcm.size:
        n_out = int(round(pcm.size * SAMPLE_RATE / rate))
        x_old = np.linspace(0.0, 1.0, num=pcm.size, endpoint=False)
        x_new = np.linspace(0.0, 1.0, num=n_out, endpoint=False)
        pcm = np.interp(x_new, x_old, pcm).astype(np.float32)
    return np.clip(pcm, -1.0, 1.0).astype(np.float32)


# Cap TTS inject so mic is not blocked for 20s of SAPI
INJECT_MAX_SAMPLES = SAMPLE_RATE * 8  # 8s


class InjectableUplinkTrack(MediaStreamTrack):
    """Uplink: short inject queue (context TTS) then live mic.

    Wingman listens to audio; DC text inject is best-effort only.
    """

    kind = "audio"

    def __init__(self, base: Optional[MediaStreamTrack] = None):
        super().__init__()
        self._base = base
        self._pts = 0
        self._start = time.monotonic()
        self._inject = np.zeros(0, dtype=np.float32)
        self._lock = threading.Lock()
        self._muted_base = False
        self._frames = 0
        self._last_peak_log = 0.0
        self._source = "silence"  # inject | mic | silence
        self.last_peak = 0.0
        self.mic_frames = 0
        self.inject_frames = 0

    def set_muted(self, muted: bool) -> None:
        """Mute only the live mic base — injects still play."""
        self._muted_base = bool(muted)
        if self._base is not None and hasattr(self._base, "set_muted"):
            self._base.set_muted(self._muted_base)

    def inject_pcm(self, mono: np.ndarray) -> int:
        mono = np.asarray(mono, dtype=np.float32).reshape(-1)
        if mono.size == 0:
            return 0
        if mono.size > INJECT_MAX_SAMPLES:
            mono = mono[:INJECT_MAX_SAMPLES]
        with self._lock:
            self._inject = (
                np.concatenate([self._inject, mono])
                if self._inject.size
                else mono.copy()
            )
            if self._inject.size > INJECT_MAX_SAMPLES:
                self._inject = self._inject[:INJECT_MAX_SAMPLES]
            return int(self._inject.size)

    def inject_wav(self, wav_path: str | Path) -> int:
        return self.inject_pcm(_load_wav_mono_48k(wav_path))

    def inject_queue_samples(self) -> int:
        with self._lock:
            return int(self._inject.size)

    def clear_inject(self) -> None:
        with self._lock:
            self._inject = np.zeros(0, dtype=np.float32)

    def _take_inject(self, n: int) -> np.ndarray:
        with self._lock:
            if self._inject.size == 0:
                return np.zeros(n, dtype=np.float32)
            take = self._inject[:n]
            self._inject = self._inject[n:]
            if take.size < n:
                take = np.pad(take, (0, n - take.size))
            return take

    def _frame_from_base(self, base_fr: AudioFrame) -> np.ndarray:
        """Normalize any base AudioFrame to float32 mono FRAME_SAMPLES."""
        arr = base_fr.to_ndarray()
        if arr.ndim > 1:
            # planar: (ch, n) or interleaved (n, ch)
            if arr.shape[0] <= 8 and arr.shape[0] < arr.shape[-1]:
                arr = arr.mean(axis=0)
            else:
                arr = arr.mean(axis=-1)
        samples = np.asarray(arr, dtype=np.float32).reshape(-1)
        # int PCM often arrives as int16/int32 ndarray
        if samples.dtype == np.int16 or (
            samples.size and float(np.max(np.abs(samples))) > 1.5
        ):
            peak = float(np.max(np.abs(samples))) if samples.size else 0.0
            if peak > 200.0:  # clearly integer PCM
                samples = samples / (32768.0 if peak <= 32768 * 1.5 else peak)
            elif base_fr.format and base_fr.format.name in ("s16", "s16p"):
                samples = samples / 32768.0
        if samples.size < FRAME_SAMPLES:
            samples = np.pad(samples, (0, FRAME_SAMPLES - samples.size))
        else:
            samples = samples[:FRAME_SAMPLES]
        return samples.astype(np.float32)

    async def recv(self) -> AudioFrame:
        if self.readyState != "live":
            raise MediaStreamError

        target = self._start + (self._pts / SAMPLE_RATE)
        delay = target - time.monotonic()
        if delay > 0.001:
            await asyncio.sleep(delay)

        source = "silence"
        if self.inject_queue_samples() > 0:
            samples = self._take_inject(FRAME_SAMPLES)
            source = "inject"
            self.inject_frames += 1
        elif self._base is not None and not self._muted_base:
            try:
                # Realign base clock once so post-inject mic isn't stuck
                if hasattr(self._base, "resync_clock"):
                    if self.inject_frames and self.mic_frames == 0:
                        self._base.resync_clock()
                base_fr = await self._base.recv()
                samples = self._frame_from_base(base_fr)
                source = "mic"
                self.mic_frames += 1
            except Exception as e:
                samples = np.zeros(FRAME_SAMPLES, dtype=np.float32)
                source = f"mic_err:{type(e).__name__}"
        else:
            samples = np.zeros(FRAME_SAMPLES, dtype=np.float32)

        self._source = source
        peak = float(np.max(np.abs(samples))) if samples.size else 0.0
        self.last_peak = peak
        self._frames += 1
        now = time.monotonic()
        if now - self._last_peak_log >= 2.0:
            self._last_peak_log = now
            print(
                f"uplink: src={source} peak={peak:.3f} "
                f"mic_frames={self.mic_frames} inject_q={self.inject_queue_samples()}",
                flush=True,
            )

        pcm = (np.clip(samples, -1.0, 1.0) * 32767.0).astype(np.int16)
        frame = AudioFrame(format="s16", layout="mono", samples=FRAME_SAMPLES)
        frame.sample_rate = SAMPLE_RATE
        frame.planes[0].update(pcm.tobytes())
        frame.pts = self._pts
        frame.time_base = fractions.Fraction(1, SAMPLE_RATE)
        self._pts += FRAME_SAMPLES
        return frame

    def stop(self) -> None:
        if self._base is not None:
            try:
                self._base.stop()
            except Exception:
                pass
            self._base = None
        super().stop()


class WavUplinkTrack(InjectableUplinkTrack):
    """Back-compat: play one WAV then fall through to base."""

    def __init__(self, wav_path: str | Path, *, after: Optional[MediaStreamTrack] = None):
        super().__init__(base=after)
        try:
            self.inject_wav(wav_path)
        except Exception:
            pass
