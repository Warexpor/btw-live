"""Local mic + speaker for aiortc — safe levels, resampled, ring-buffered."""
from __future__ import annotations

import asyncio
import fractions
import threading
import time
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
            mono = _limit(mono, gain=self._gain, peak=SPEAKER_PEAK_LIMIT)
            self._ring.write(mono)
            self._frames_in += 1
            if not self._ready and self._ring.size >= SPEAKER_PREROLL:
                self._ready = True

    def stop(self) -> None:
        self._ready = False
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
