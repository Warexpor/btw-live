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
SPEAKER_GAIN = 0.28
SPEAKER_PEAK_LIMIT = 0.40
# Playout jitter buffer. Logs showed chronic full underruns with 40 ms cushion
# (u≈8% of pulls, ring stuck at 1–2 frames, drop=0). WebRTC arrives unevenly;
# starving the PortAudio callback → audible stutters mid-speech.
SPEAKER_PREROLL = int(SAMPLE_RATE * 0.12)  # 120 ms before first play
# Crossfade only on real discontinuities (inject↔mic), not every speech frame
DECLICK_SAMPLES = 64
# Only treat near-digital jumps as decode glitches (speech legitimately jumps more)
CLICK_JUMP = 0.85
# Post-gain packet joins: must stay HIGH. At 0.08 almost every WebRTC packet
# boundary re-blended → warble/stutter on continuous speech (log + theory).
SPEAKER_JOIN_JUMP = 0.28
SPEAKER_JOIN_SAMPLES = 48
# Steady playout depth + room for network jitter without multi-second lag
SPEAKER_TARGET = int(SAMPLE_RATE * 0.10)  # ~100 ms
SPEAKER_HIGH = int(SAMPLE_RATE * 0.18)  # nibble above ~180 ms
SPEAKER_RING_MAX = int(SAMPLE_RATE * 0.32)  # hard cap ~320 ms
# Treat "recent remote audio" for underrun diagnostics / silence vs mid-speech
SPEAKER_ACTIVE_S = 0.25


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

    def drop_to(self, max_keep: int) -> int:
        """Discard oldest samples so size <= max_keep. Returns count dropped."""
        max_keep = max(0, int(max_keep))
        with self._lock:
            if self._size <= max_keep:
                return 0
            drop = self._size - max_keep
            self._r = (self._r + drop) % self._cap
            self._size -= drop
            return drop

    @property
    def size(self) -> int:
        with self._lock:
            return self._size


# Keep only ~this much mic backlog (ms of "now"). Larger backlog = delayed
# utterance dump after you stop talking — kills barge-in vs real ChatGPT Live.
MIC_LIVE_EDGE_SAMPLES = int(SAMPLE_RATE * 0.06)  # 60 ms


def _to_mono_float(arr: np.ndarray) -> np.ndarray:
    a = np.asarray(arr)
    if a.size == 0:
        return np.zeros(0, dtype=np.float32)
    src_dtype = a.dtype
    if a.ndim == 1:
        mono = a
    elif a.shape[0] <= 8 and a.shape[0] < a.shape[-1]:
        mono = a.mean(axis=0)
    else:
        mono = a.mean(axis=-1)
    mono = np.asarray(mono, dtype=np.float64).reshape(-1)
    # int paths — check source dtype before float cast lost it
    if src_dtype == np.int16:
        mono = mono / 32768.0
    elif src_dtype == np.int32:
        mono = mono / 2147483648.0
    elif src_dtype == np.uint8:
        mono = (mono - 128.0) / 128.0
    # already float: assume [-1,1]; if clearly not, scale down
    peak = float(np.max(np.abs(mono))) if mono.size else 0.0
    if peak > 8.0:
        # likely wrong dtype interpretation — kill it
        return np.zeros(mono.size, dtype=np.float32)
    if peak > 1.5:
        mono = mono / peak
    return mono.astype(np.float32)


class _Envelope:
    """Display meter: instant attack, slow release. Values stay in ~[0, 1]."""

    __slots__ = ("value", "release")

    def __init__(self, release: float = 0.90):
        self.value = 0.0
        self.release = float(release)

    def update(self, x: float) -> float:
        x = abs(float(x) or 0.0)
        if x >= self.value:
            self.value = x
        else:
            r = self.release
            self.value = self.value * r + x * (1.0 - r)
        if self.value < 1e-4:
            self.value = 0.0
        return self.value

    def reset(self) -> None:
        self.value = 0.0


def _frame_level(samples: np.ndarray) -> float:
    """Continuous 0..1 energy for meters (RMS-weighted, not single-sample spike)."""
    if samples is None or samples.size == 0:
        return 0.0
    x = np.asarray(samples, dtype=np.float32).reshape(-1)
    peak = float(np.max(np.abs(x)))
    # RMS tracks speech better than pure peak between phonemes
    rms = float(np.sqrt(np.mean(np.square(x)))) if x.size else 0.0
    # blend: peak for attacks, RMS for body; mild headroom so speech isn't pegged
    return min(1.0, max(peak * 0.55, rms * 3.0))


def _limit(mono: np.ndarray, gain: float = SPEAKER_GAIN, peak: float = SPEAKER_PEAK_LIMIT) -> np.ndarray:
    """Gain + hard peak limit. No tanh — soft clip was warping speech into grit."""
    x = mono * gain
    return np.clip(x, -peak, peak).astype(np.float32)


def _declick_join(
    prev_last: float,
    mono: np.ndarray,
    n: int = DECLICK_SAMPLES,
    *,
    jump_thresh: float = 0.45,
) -> np.ndarray:
    """Blend only on large discontinuities (e.g. inject↔mic). Leave speech alone.

    jump_thresh: abs step from prev_last → mono[0] required to crossfade.
    Full-scale uplink uses ~0.45; post-gain speaker (~0.4 max) uses SPEAKER_JOIN_JUMP.
    """
    mono = np.asarray(mono, dtype=np.float32).reshape(-1)
    if mono.size == 0:
        return mono
    jump = float(mono[0]) - float(prev_last)
    if abs(jump) < float(jump_thresh):
        return mono
    n = int(min(max(4, n), mono.size))
    out = mono.copy()
    fade = np.linspace(0.0, 1.0, n, dtype=np.float32)
    held = np.full(n, float(prev_last), dtype=np.float32)
    out[:n] = held * (1.0 - fade) + out[:n] * fade
    return out


def _speaker_pull_block(
    ring: _FloatRing,
    frames: int,
    last_played: float,
) -> tuple[np.ndarray, float, bool]:
    """Pull one output block. Never hard-zero a shortfall (that clicks).

    Returns (mono, new_last_played, starved).
    starved=True when the ring could not fully supply `frames` samples.
    """
    frames = int(frames)
    if frames <= 0:
        return np.zeros(0, dtype=np.float32), float(last_played), False
    have = ring.size
    if have <= 0:
        mono = _fade_from_hold(last_played, frames)
        last = float(mono[-1]) if mono.size else 0.0
        return mono, last, True
    if have < frames:
        head = ring.read(have)
        hold = float(head[-1]) if head.size else float(last_played)
        tail = _fade_from_hold(hold, frames - have)
        mono = np.concatenate([head, tail]) if head.size else tail
        last = float(mono[-1]) if mono.size else 0.0
        return mono, last, True
    mono = ring.read(frames)
    last = float(mono[-1]) if mono.size else 0.0
    return mono, last, False


def _soften_intra_clicks(mono: np.ndarray, jump: float = CLICK_JUMP) -> np.ndarray:
    """Kill rare one-sample digital spikes only. Low thresholds scratch speech."""
    mono = np.asarray(mono, dtype=np.float32).reshape(-1)
    if mono.size < 3:
        return mono
    # Fast path: no extreme sample → leave untouched (common case)
    peak = float(np.max(np.abs(mono)))
    if peak < 0.92:
        return mono
    out = mono
    d = np.abs(np.diff(out))
    bad = np.where(d > jump)[0]
    if bad.size == 0:
        return mono
    out = mono.copy()
    for i in bad:
        i1 = i + 1
        if i1 >= out.size:
            continue
        # single-sample spike: neighbors agree
        if i1 + 1 < out.size and abs(out[i1 + 1] - out[i]) < jump * 0.4:
            out[i1] = 0.5 * (out[i] + out[i1 + 1])
        elif abs(out[i1]) > 0.9:
            out[i1] = out[i]
    return out


def _fade_from_hold(hold: float, n: int, decay: float = 0.985) -> np.ndarray:
    """Short underrun fill — decay fast so we don't invent humming scratch."""
    if n <= 0:
        return np.zeros(0, dtype=np.float32)
    if abs(hold) < 1e-4:
        return np.zeros(n, dtype=np.float32)
    t = np.arange(n, dtype=np.float32)
    return (float(hold) * (decay ** t)).astype(np.float32)


class MicrophoneTrack(MediaStreamTrack):
    """Capture mic continuously. Prefer live edge over delayed backlog.

    When used under InjectableUplinkTrack, set paced=False so only the
    outer track sleeps for 20 ms frames. Double pacing was causing catch-up
    dumps: whole utterances arrive after you stop → no barge-in.
    """

    kind = "audio"

    def __init__(self, device: Optional[int | str] = None, *, paced: bool = True):
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
        # Outer InjectableUplinkTrack owns WebRTC frame clock when False.
        self._paced = bool(paced)

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
            latency="low",
            callback=callback,
        )
        self._stream.start()

    def resync_clock(self) -> None:
        """Snap to live edge after inject / stall — no delayed dump."""
        self._started = time.monotonic()
        self._pts = 0
        self._pending = np.zeros(0, dtype=np.float32)
        self._ring = _FloatRing(SAMPLE_RATE * RING_SECONDS)

    def discard_buffered(self) -> None:
        """Drop ring + pending (call every inject frame so mic stays live-edge)."""
        self._pending = np.zeros(0, dtype=np.float32)
        self._ring.drop_to(0)

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

    def _need_in(self) -> int:
        if self._in_rate == SAMPLE_RATE:
            return FRAME_SAMPLES
        return int(round(FRAME_SAMPLES * self._in_rate / SAMPLE_RATE))

    async def _pull_live_frame(self) -> np.ndarray:
        """One frame of *current* mic audio; drop backlog older than live edge."""
        need_in = self._need_in()
        # Keep only ~60ms + one frame of "now". Shipping older backlog makes
        # Wingman hear your full sentence after you already stopped.
        edge_in = need_in + int(
            round(MIC_LIVE_EDGE_SAMPLES * self._in_rate / SAMPLE_RATE)
        )
        pending_n = int(self._pending.size)
        self._ring.drop_to(max(0, edge_in - pending_n))

        chunks = [self._pending]
        got = pending_n
        # Short waits only when under-running (startup / glitch). Max ~16ms.
        tries = 0
        max_tries = 8 if not self._paced else 20
        while got < need_in and tries < max_tries:
            chunk = self._ring.read(need_in - got)
            chunks.append(chunk)
            got += chunk.size
            if got < need_in:
                await asyncio.sleep(0.002)
            tries += 1

        raw = np.concatenate(chunks) if chunks else np.zeros(0, dtype=np.float32)
        if raw.size < need_in:
            raw = np.pad(raw, (0, need_in - raw.size))
        self._pending = (
            raw[need_in:] if raw.size > need_in else np.zeros(0, dtype=np.float32)
        )
        if self.muted:
            return np.zeros(FRAME_SAMPLES, dtype=np.float32)
        samples = self._resample_to_48k(raw[:need_in], self._in_rate)
        if samples.size < FRAME_SAMPLES:
            samples = np.pad(samples, (0, FRAME_SAMPLES - samples.size))
        else:
            samples = samples[:FRAME_SAMPLES]
        return np.clip(samples * 0.9, -1.0, 1.0).astype(np.float32)

    async def recv(self) -> AudioFrame:
        if self.readyState != "live":
            raise MediaStreamError

        if self._paced:
            target = self._started + (self._pts / SAMPLE_RATE)
            delay = target - time.monotonic()
            if delay > 0.001:
                await asyncio.sleep(delay)
            # >40ms late → jump to live edge instead of dumping backlog
            elif delay < -0.040:
                self.resync_clock()

        samples = await self._pull_live_frame()

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
    """Remote audio → speakers with underrun/glitch smoothing.

    Cracks often come from (a) ring underruns → hard zeros, (b) decode spikes,
    (c) discontinuous packet / drop joins. We do not invent missing OpenAI
    audio, but we *do* fade shortfalls and declick real edges only.
    """

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
        self._env = _Envelope(release=0.91)
        self._last_audio_ts = 0.0
        self.last_peak = 0.0  # envelope level for visualizer (0..1)
        # de-click state (callback + push path)
        self._last_played = 0.0
        self._last_written = 0.0
        self._write_lock = threading.Lock()
        self._starved = False
        self._need_join = False  # set after lag drop — next play block blends
        # diagnostics (surfaced in stats())
        self.underruns = 0  # mid-speech only (recent remote audio)
        self.silence_underruns = 0  # expected when she pauses
        self.partial_underruns = 0
        self.ring_drops = 0
        self.sd_underflows = 0

    def sample_meter(self) -> float:
        """Envelope level; releases when no remote frames recently."""
        if self._last_audio_ts and (time.monotonic() - self._last_audio_ts) > 0.05:
            self.last_peak = self._env.update(0.0)
        return float(self.last_peak)

    def _audio_active(self) -> bool:
        if not self._last_audio_ts:
            return False
        return (time.monotonic() - self._last_audio_ts) < SPEAKER_ACTIVE_S

    def stats(self) -> dict:
        return {
            "frames_in": self._frames_in,
            "ring": self._ring.size,
            "underruns": self.underruns,
            "silence_underruns": self.silence_underruns,
            "partial_underruns": self.partial_underruns,
            "ring_drops": self.ring_drops,
            "sd_underflows": self.sd_underflows,
            "active": self._audio_active(),
        }

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
            # Play path must stay cheap — no per-block speech smear.
            if status:
                try:
                    # PortAudio / sounddevice underflow flag
                    if bool(status):
                        player.sd_underflows += 1
                except Exception:
                    pass

            have = player._ring.size
            if not player._ready:
                if have >= SPEAKER_PREROLL:
                    player._ready = True
                else:
                    outdata.fill(0)
                    player._last_played = 0.0
                    player._starved = False
                    return

            was_starved = player._starved
            need_join = player._need_join
            mono, last, starved = _speaker_pull_block(
                player._ring, frames, player._last_played
            )
            if starved:
                # Silence gaps are normal (she pauses). Mid-speech empty ring = stutter.
                if player._audio_active():
                    if have <= 0:
                        player.underruns += 1
                    else:
                        player.partial_underruns += 1
                else:
                    player.silence_underruns += 1
                    # Don't invent hold-tone during quiet; zeros are clean silence
                    if abs(float(player._last_played)) < 1e-3:
                        mono = np.zeros(frames, dtype=np.float32)
                        last = 0.0
            # After mid-speech underrun or lag-drop only — not every packet
            if (was_starved or need_join) and not starved and mono.size:
                mono = _declick_join(
                    player._last_played,
                    mono,
                    n=SPEAKER_JOIN_SAMPLES,
                    jump_thresh=SPEAKER_JOIN_JUMP,
                )
                last = float(mono[-1]) if mono.size else last
                player._need_join = False
            player._starved = starved
            player._last_played = last

            # already limited on write — only hard-safety here
            mono = np.clip(mono, -SPEAKER_PEAK_LIMIT, SPEAKER_PEAK_LIMIT)
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
            # Slightly above "low": fewer host buffer hiccups; still ~1–2 frames.
            latency=0.06,
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
            raw_peak = float(np.max(np.abs(mono))) if mono.size else 0.0
            if raw_peak > 0.99 and self._frames_in < 5:
                continue
            # Rare digital spikes only; do not re-process every speech frame
            mono = _soften_intra_clicks(mono)
            limited = _limit(mono, gain=self._gain, peak=SPEAKER_PEAK_LIMIT)
            # Join only real discontinuities (lag drop / rare decode jump).
            # Continuous speech packet edges must NOT re-blend every frame.
            with self._write_lock:
                if self._need_join or abs(float(limited[0]) - self._last_written) > SPEAKER_JOIN_JUMP:
                    limited = _declick_join(
                        self._last_written,
                        limited,
                        n=SPEAKER_JOIN_SAMPLES,
                        jump_thresh=SPEAKER_JOIN_JUMP,
                    )
                if limited.size:
                    self._last_written = float(limited[-1])
            heard = _frame_level(limited / max(SPEAKER_PEAK_LIMIT, 1e-6))
            self.last_peak = self._env.update(heard)
            self._last_audio_ts = time.monotonic()
            self._ring.write(limited)
            # Keep playout near target: trim when high water, hard-cap always
            size = self._ring.size
            if size > SPEAKER_RING_MAX:
                dropped = self._ring.drop_to(SPEAKER_TARGET)
            elif size > SPEAKER_HIGH:
                # Nibble toward target (one frame per write) — soft catch-up
                keep = max(SPEAKER_TARGET, size - FRAME_SAMPLES)
                dropped = self._ring.drop_to(keep)
            else:
                dropped = 0
            if dropped:
                self.ring_drops += 1
                self._need_join = True
            self._frames_in += 1
            if not self._ready and self._ring.size >= SPEAKER_PREROLL:
                self._ready = True

    def stop(self) -> None:
        self._ready = False
        self.last_peak = 0.0
        self._last_audio_ts = 0.0
        self._last_played = 0.0
        self._last_written = 0.0
        self._starved = False
        self._need_join = False
        self._env.reset()
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


# Cap TTS inject — boot can run up to ~1 min of SAPI for a dense brief
INJECT_MAX_SAMPLES = SAMPLE_RATE * 60  # 60s


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
        self._env = _Envelope(release=0.90)
        self.last_peak = 0.0  # envelope level for visualizer (0..1)
        self.mic_frames = 0
        self.inject_frames = 0
        self._last_sample = 0.0

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
        """Normalize any base AudioFrame to float32 mono FRAME_SAMPLES @ [-1,1]."""
        try:
            arr = base_fr.to_ndarray()
        except Exception:
            try:
                raw = bytes(base_fr.planes[0])
                arr = np.frombuffer(raw, dtype=np.int16)
            except Exception:
                return np.zeros(FRAME_SAMPLES, dtype=np.float32)

        # Prefer format-aware scale: MicrophoneTrack emits s16 mono frames.
        fmt = ""
        try:
            fmt = (base_fr.format.name if base_fr.format else "") or ""
        except Exception:
            fmt = ""

        if arr.ndim > 1:
            if arr.shape[0] <= 8 and arr.shape[0] < arr.shape[-1]:
                arr = arr.mean(axis=0)
            else:
                arr = arr.mean(axis=-1)

        src_dtype = getattr(arr, "dtype", None)
        samples = np.asarray(arr, dtype=np.float64).reshape(-1)

        if src_dtype == np.int16 or fmt in ("s16", "s16p"):
            samples = samples / 32768.0
        elif src_dtype == np.int32 or fmt in ("s32", "s32p"):
            samples = samples / 2147483648.0
        else:
            peak = float(np.max(np.abs(samples))) if samples.size else 0.0
            if peak > 200.0:
                # float view of integer PCM
                samples = samples / (32768.0 if peak <= 32768 * 1.5 else peak)
            elif peak > 1.5:
                samples = samples / peak

        if samples.size < FRAME_SAMPLES:
            samples = np.pad(samples, (0, FRAME_SAMPLES - samples.size))
        else:
            samples = samples[:FRAME_SAMPLES]
        return np.clip(samples, -1.0, 1.0).astype(np.float32)

    async def recv(self) -> AudioFrame:
        if self.readyState != "live":
            raise MediaStreamError

        # Sole WebRTC pacer (mic base uses paced=False). Cap catch-up so we
        # never blast a backlog of speech after a stall.
        target = self._start + (self._pts / SAMPLE_RATE)
        delay = target - time.monotonic()
        if delay > 0.001:
            await asyncio.sleep(delay)
        elif delay < -0.040:
            # Jump timeline to now; mic live-edge drop handles samples.
            self._start = time.monotonic()
            self._pts = 0
            if self._base is not None and hasattr(self._base, "resync_clock"):
                try:
                    self._base.resync_clock()
                except Exception:
                    pass

        source = "silence"
        if self.inject_queue_samples() > 0:
            samples = self._take_inject(FRAME_SAMPLES)
            source = "inject"
            self.inject_frames += 1
            # Keep mic ring at live edge while inject owns uplink (no post-TTS dump)
            if self._base is not None and hasattr(self._base, "discard_buffered"):
                try:
                    self._base.discard_buffered()
                except Exception:
                    pass
        elif self._base is not None and not self._muted_base:
            try:
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

        # Only blend inject↔mic edges (high threshold). No per-frame soften on speech.
        samples = _declick_join(self._last_sample, samples)
        if samples.size:
            self._last_sample = float(samples[-1])

        self._source = source
        instant = _frame_level(samples)
        self.last_peak = self._env.update(instant)
        self._frames += 1
        now = time.monotonic()
        if now - self._last_peak_log >= 2.0:
            self._last_peak_log = now
            print(
                f"uplink: src={source} peak={instant:.3f} meter={self.last_peak:.3f} "
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
        self._env.reset()
        self.last_peak = 0.0
        self._last_sample = 0.0
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
