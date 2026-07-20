"""Standalone Live session: mint + aiortc + local audio + control IPC.

Context delivery (product):
  Plain-text datachannel entries — not TTS, not Realtime JSON envelopes.
  Realtime-style session.update/response.create often closes Wingman PC.

  - On DC open: plain-text session brief + context entries
  - Mid-call top-up: plain-text entry on open DC
  - Optional audio TTS only if BTW_AUDIO_BOOT / BTW_AUDIO_TOPUP = 1
  - Optional Realtime JSON only if BTW_DC_REALTIME = 1
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from typing import Any, Callable, Optional

from aiortc import RTCPeerConnection, RTCSessionDescription

from .audio_io import (
    InjectableUplinkTrack,
    MicrophoneTrack,
    SilentTrack,
    SpeakerPlayer,
    synthesize_speech_wav,
)
from .control import clear_commands, drain_commands, write_live_status, write_meters
from .http_client import ChatGPTClient
from .paths import data_dir
from .profiles import SessionProfile, load_profile
from .session_json import (
    build_voice_session_payload,
    context_push_events,
    instruction_events,
    plain_boot_entries,
    plain_topup_entry,
)

log = logging.getLogger("btw.live")

# Keep spoken injects short — long TTS blocks the mic
AUDIO_BRIEF_MAX = 320
AUDIO_TOPUP_MAX = 280


def _log(msg: str) -> None:
    log.info(msg)
    print(msg, flush=True)


def _dc_to_text(message: Any) -> str:
    if isinstance(message, str):
        return message
    if isinstance(message, (bytes, bytearray, memoryview)):
        return bytes(message).decode("utf-8", errors="replace")
    return repr(message)


def _clip(text: str, limit: int) -> str:
    t = (text or "").strip()
    if len(t) <= limit:
        return t
    return t[:limit] + " …"


def spoken_bootstrap(instructions: str, context: str = "") -> str:
    """What we speak at call start so the voice agent has session ground truth."""
    ctx = (context or "").strip()
    ins = (instructions or "").strip()
    body = ctx if ctx else ins
    body = _clip(body, AUDIO_BRIEF_MAX)
    if not body:
        return (
            "BTW V C session. You are a voice advisor for a Grok Build coding "
            "session. You cannot edit files. Wait for the user."
        )
    return (
        "Session brief. Voice advisor for Grok Build. Cannot edit files. "
        f"Context: {body}"
    )


def spoken_topup(delta: str) -> str:
    """What we speak when context is topped up mid-call."""
    d = _clip(delta, AUDIO_TOPUP_MAX)
    if not d:
        return ""
    return (
        "Context update. Add this to the session facts and keep prior context. "
        f"{d}"
    )


class LiveSession:
    def __init__(
        self,
        profile: SessionProfile,
        instructions: str,
        *,
        use_mic: bool = True,
        use_speaker: bool = True,
        session_name: str = "default",
        muted: bool = False,
        voice: str | None = None,
        on_dc_message: Optional[Callable[[str], None]] = None,
        context: str = "",
    ):
        self.profile = profile
        self.instructions = instructions
        self.context = context or ""
        self.use_mic = use_mic
        self.use_speaker = use_speaker
        self.session_name = session_name
        self.voice = voice or profile.voice
        self.on_dc_message = on_dc_message
        self.client = ChatGPTClient()
        self.pc: Optional[RTCPeerConnection] = None
        self.speaker: Optional[SpeakerPlayer] = None
        self.mic_track: Optional[InjectableUplinkTrack] = None
        self.voice_session_id = str(uuid.uuid4()).upper()
        self.stats: dict[str, Any] = {}
        self._dc = None
        self._closed = asyncio.Event()
        self._muted = bool(muted)
        self._stop_requested = False
        self._inbox_path = data_dir() / "dc_inbox.jsonl"

    def set_muted(self, muted: bool) -> None:
        self._muted = bool(muted)
        if self.mic_track is not None:
            self.mic_track.set_muted(self._muted)
        self.stats["muted"] = self._muted
        _log(f"mic muted={self._muted}")
        self._publish_status()

    def _meter_snapshot(self) -> dict[str, Any]:
        up = (
            float(getattr(self.mic_track, "last_peak", 0.0) or 0.0)
            if self.mic_track
            else 0.0
        )
        down = 0.0
        if self.speaker is not None:
            down = float(getattr(self.speaker, "last_peak", 0.0) or 0.0)
            # Decay when no remote frames arrive (push_frame holds peak up)
            try:
                self.speaker.last_peak = down * 0.88
            except Exception:
                pass
        injecting = False
        uplink_src = None
        mic_frames = 0
        if self.mic_track is not None:
            uplink_src = getattr(self.mic_track, "_source", None)
            mic_frames = int(getattr(self.mic_track, "mic_frames", 0) or 0)
            try:
                injecting = (
                    self.mic_track.inject_queue_samples() > 0
                    or str(uplink_src or "") == "inject"
                )
            except Exception:
                injecting = str(uplink_src or "") == "inject"
        live = bool(self.pc and not self._closed.is_set())
        return {
            "status": "live" if live else "idle",
            "session_name": self.session_name,
            "profile": self.profile.name,
            "voice": self.voice,
            "muted": self._muted,
            "injecting": injecting,
            "uplink_peak": up,
            "downlink_peak": down,
            "uplink_src": uplink_src,
            "mic_frames": mic_frames,
            "pc": self.stats.get("pc_state"),
            "ice": self.stats.get("ice_state"),
            "dc_open": bool(self.stats.get("dc_open")),
            "audio_injects": self.stats.get("audio_injects", 0),
            "last_audio_inject": self.stats.get("last_audio_inject"),
        }

    def _publish_meters(self) -> None:
        write_meters(self._meter_snapshot())

    def _publish_status(self) -> None:
        snap = self._meter_snapshot()
        write_live_status(
            {
                **snap,
                "voice_session_id": self.voice_session_id,
                "mic": self.stats.get("mic"),
                "instructions_chars": len(self.instructions or ""),
                "context_chars": len(self.context or ""),
            }
        )
        write_meters(snap)

    def _append_inbox(self, direction: str, text: str, meta: dict[str, Any] | None = None) -> None:
        rec = {"ts": time.time(), "dir": direction, "text": text[:8000], **(meta or {})}
        try:
            with self._inbox_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except Exception:
            pass

    @staticmethod
    def _env_flag(name: str) -> bool:
        return os.environ.get(name, "").strip().lower() in ("1", "true", "yes")

    def _send_events(self, channel, events: list[dict[str, Any]], tag: str) -> int:
        n = 0
        for ev in events:
            try:
                raw = json.dumps(ev, ensure_ascii=False)
                channel.send(raw)
                self.stats.setdefault("dc_events", []).append(ev.get("type"))
                self._append_inbox("out", raw, {"tag": tag, "type": ev.get("type")})
                _log(f"dc_send[{tag}] {ev.get('type')} bytes={len(raw)}")
                n += 1
            except Exception as e:
                _log(f"dc_send err: {e}")
        return n

    def _send_plain_texts(self, channel, texts: list[str], tag: str) -> int:
        """Product path: raw UTF-8 strings on the datachannel (not Realtime JSON)."""
        n = 0
        for i, text in enumerate(texts):
            t = (text or "").strip()
            if not t:
                continue
            try:
                channel.send(t)
                self.stats.setdefault("dc_events", []).append("plain_text")
                self._append_inbox(
                    "out", t, {"tag": tag, "type": "plain_text", "i": i}
                )
                _log(f"dc_plain[{tag}] i={i} chars={len(t)}")
                n += 1
            except Exception as e:
                _log(f"dc_plain err: {e}")
        return n

    def _boot_inject_sync(self, channel) -> None:
        """Inject session brief + context as plain text on DC open."""
        try:
            if getattr(channel, "readyState", None) != "open":
                return
            if self._env_flag("BTW_DC_REALTIME"):
                n = self._send_events(
                    channel, instruction_events(self.instructions), "boot"
                )
                self.stats["boot_events"] = n
                self.stats["dc_injection_sent"] = n > 0
                _log(f"boot_dc realtime sent={n} ready={getattr(channel, 'readyState', '?')}")
                return

            entries = plain_boot_entries(self.instructions, self.context)
            n = self._send_plain_texts(channel, entries, "boot")
            self.stats["boot_events"] = n
            self.stats["dc_injection_sent"] = n > 0
            _log(
                f"boot_dc plain sent={n} entries ready={getattr(channel, 'readyState', '?')}"
            )
        except Exception as e:
            _log(f"boot_inject err: {e}")

    def speak_text(self, text: str, *, tag: str = "speak") -> bool:
        """Queue TTS onto the uplink (opt-in fallback only)."""
        t = (text or "").strip()
        if not t:
            return False
        if self.mic_track is None:
            _log(f"speak_text[{tag}]: no uplink track")
            return False
        try:
            path = data_dir() / f"inject_{tag}.wav"
            synthesize_speech_wav(t, path, rate=1)
            n = self.mic_track.inject_wav(path)
            self.stats["audio_injects"] = int(self.stats.get("audio_injects") or 0) + 1
            self.stats["last_audio_inject"] = tag
            self.stats["last_audio_chars"] = len(t)
            _log(f"audio_inject[{tag}] chars={len(t)} samples={n}")
            self._publish_status()
            return n > 0
        except Exception as e:
            _log(f"audio_inject[{tag}] err: {e}")
            return False

    def speak_bootstrap(self) -> bool:
        """Audio bootstrap — off unless BTW_AUDIO_BOOT=1 (plain text is primary)."""
        if not self._env_flag("BTW_AUDIO_BOOT"):
            _log("audio bootstrap skipped (plain-text DC is primary; BTW_AUDIO_BOOT=1 to force)")
            self.stats["bootstrap"] = False
            return False
        return self.speak_text(
            spoken_bootstrap(self.instructions, self.context), tag="bootstrap"
        )

    def speak_context_topup(self, delta: str) -> bool:
        if not self._env_flag("BTW_AUDIO_TOPUP"):
            return False
        return self.speak_text(spoken_topup(delta), tag="topup")

    def reinject_instructions(self, instructions: str | None = None) -> bool:
        if instructions is not None:
            self.instructions = instructions
        ch = self._dc
        ok_dc = False
        if ch and getattr(ch, "readyState", None) == "open":
            if self._env_flag("BTW_DC_REALTIME"):
                self._send_events(
                    ch, instruction_events(self.instructions), "reinject"
                )
            else:
                self._send_plain_texts(
                    ch,
                    plain_boot_entries(self.instructions, self.context),
                    "reinject",
                )
            ok_dc = True
        else:
            _log("reinject: no open datachannel")
        ok_audio = False
        if self._env_flag("BTW_AUDIO_BOOT"):
            ok_audio = self.speak_text(
                spoken_bootstrap(self.instructions, self.context), tag="reinject"
            )
        return ok_audio or ok_dc

    def push_context_live(
        self, context_delta: str, *, full_context: str | None = None
    ) -> bool:
        """Top-up context mid-call: store + plain-text DC entry (+ optional TTS)."""
        delta = (context_delta or "").strip()
        if full_context is not None:
            self.context = full_context
        elif delta:
            if self.context.strip():
                self.context = self.context.rstrip() + "\n\n" + delta
            else:
                self.context = delta
        try:
            self.instructions = self.profile.assemble_instructions(self.context)
            (data_dir() / "instructions.txt").write_text(
                self.instructions, encoding="utf-8"
            )
            (data_dir() / "context.txt").write_text(self.context, encoding="utf-8")
        except Exception as e:
            _log(f"push_context file write: {e}")

        ok_dc = False
        ch = self._dc
        if ch and getattr(ch, "readyState", None) == "open" and delta:
            if self._env_flag("BTW_DC_REALTIME"):
                self._send_events(ch, context_push_events(delta), "context")
            else:
                entry = plain_topup_entry(delta)
                self._send_plain_texts(ch, [entry] if entry else [], "context")
            ok_dc = True
        elif delta:
            _log("push_context: DC closed — text not delivered")

        ok_audio = self.speak_context_topup(delta) if delta else False
        self._publish_status()
        return ok_audio or ok_dc

    def _handle_dc_message(self, message: Any, label: str) -> None:
        text = _dc_to_text(message)
        self.stats.setdefault("dc_msgs", []).append(text[:500])
        self._append_inbox("in", text, {"label": label})
        _log(f"dc_msg[{label}] {text[:200]}")
        if self.on_dc_message:
            try:
                self.on_dc_message(text)
            except Exception:
                pass

    async def start(self) -> dict[str, Any]:
        # Drop stop/mute orphans from a prior kill or ESC key-repeat so this
        # session does not die on the first control tick.
        clear_commands()
        _log(f"auth backend={self.client.backend} …")
        token = self.client.fetch_access_token()
        _log(f"accessToken ok len={len(token)}")

        pc = RTCPeerConnection()
        self.pc = pc
        self.stats = {
            "ice": [],
            "dc_events": [],
            "dc_msgs": [],
            "muted": self._muted,
            "audio_injects": 0,
            "context_chars": len(self.context or ""),
        }

        @pc.on("connectionstatechange")
        async def on_state():
            _log(f"pc_state={pc.connectionState}")
            self.stats["pc_state"] = pc.connectionState
            self._publish_status()
            if pc.connectionState in ("failed", "closed", "disconnected"):
                self._closed.set()

        @pc.on("iceconnectionstatechange")
        async def on_ice():
            _log(f"ice_state={pc.iceConnectionState}")
            self.stats["ice_state"] = pc.iceConnectionState
            self._publish_status()

        if self.use_speaker:
            try:
                self.speaker = SpeakerPlayer()
                self.speaker.start()
            except Exception as e:
                _log(f"speaker init failed: {e}")
                self.speaker = None

        @pc.on("track")
        def on_track(track):
            _log(f"ontrack kind={track.kind}")
            self.stats.setdefault("tracks", []).append(track.kind)
            speaker = self.speaker
            if track.kind == "audio" and speaker is not None:

                async def _play():
                    frames_n = 0
                    while True:
                        try:
                            frame = await track.recv()
                            await speaker.push_frame(frame)
                            frames_n += 1
                            if frames_n == 1:
                                _log("speaker: first remote audio frame")
                            if frames_n % 250 == 0:
                                _log(f"speaker: frames={frames_n}")
                        except Exception as e:
                            _log(f"play loop end frames={frames_n}: {e}")
                            break

                asyncio.ensure_future(_play())

        def wire_dc(channel, label: str):
            _log(f"dc wire {label} label={channel.label}")

            @channel.on("open")
            def on_open():
                _log(f"dc_open {label}")
                self.stats["dc_open"] = True
                self._dc = channel
                self._boot_inject_sync(channel)
                self._publish_status()

            @channel.on("message")
            def on_message(message):
                self._handle_dc_message(message, label)

            @channel.on("close")
            def on_close():
                _log(f"dc_close {label}")
                if self._dc is channel:
                    self.stats["dc_open"] = False
                self._publish_status()

            self._dc = channel

        @pc.on("datachannel")
        def on_datachannel(channel):
            wire_dc(channel, "remote")

        try:
            local_dc = pc.createDataChannel("oai-events")
            wire_dc(local_dc, "local")
        except Exception as e:
            _log(f"createDataChannel failed: {e}")

        base = None
        if self.use_mic:
            try:
                base = MicrophoneTrack()
                if self._muted:
                    base.set_muted(True)
                self.stats["mic"] = "microphone"
                _log("mic: MicrophoneTrack")
            except Exception as e:
                _log(f"mic failed ({e}); silent base")
                base = SilentTrack()
                self.stats["mic"] = "silent"
        else:
            base = SilentTrack()
            self.stats["mic"] = "silent"

        self.mic_track = InjectableUplinkTrack(base=base)
        if self._muted:
            self.mic_track.set_muted(True)
        pc.addTrack(self.mic_track)

        if self.speak_bootstrap():
            self.stats["bootstrap"] = True
            _log("bootstrap audio queued for uplink")
        else:
            self.stats["bootstrap"] = False
            _log("bootstrap audio failed or empty")

        try:
            pc.addTransceiver("video", direction="recvonly")
        except Exception:
            pass

        offer = await pc.createOffer()
        await pc.setLocalDescription(offer)

        for _ in range(50):
            if pc.iceGatheringState == "complete":
                break
            await asyncio.sleep(0.05)

        sdp_offer = pc.localDescription.sdp
        session = build_voice_session_payload(
            self.profile,
            voice_session_id=self.voice_session_id,
            voice=self.voice,
        )
        _log(f"mint offer_sdp_len={len(sdp_offer)} voice={session.get('voice')}")
        answer_sdp = self.client.mint_realtime(sdp_offer, session)
        _log(f"mint ok answer_sdp_len={len(answer_sdp)}")
        self.stats["mint"] = 201
        self.stats["answer_len"] = len(answer_sdp)

        await pc.setRemoteDescription(
            RTCSessionDescription(sdp=answer_sdp, type="answer")
        )
        self.stats["voice_session_id"] = self.voice_session_id
        self.stats["ok"] = True
        self._publish_status()
        return self.stats

    async def _control_loop(self) -> None:
        ticks = 0
        while not self._closed.is_set() and not self._stop_requested:
            for rec in drain_commands():
                cmd = (rec.get("cmd") or "").lower()
                if cmd in ("mute", "mic_mute"):
                    self.set_muted(True)
                elif cmd in ("unmute", "mic_unmute"):
                    self.set_muted(False)
                elif cmd == "stop":
                    _log("control: stop")
                    self._stop_requested = True
                    self._closed.set()
                    # Ignore rest of batch (ESC key-repeat / stacked stops).
                    break
                elif cmd == "reinject":
                    if rec.get("instructions"):
                        self.instructions = rec["instructions"]
                    if rec.get("context") is not None:
                        self.context = rec.get("context") or ""
                    self.reinject_instructions()
                elif cmd in ("push_context", "speak_context", "topup_context"):
                    delta = rec.get("context") or rec.get("text") or ""
                    full = rec.get("full_context")
                    self.push_context_live(delta, full_context=full)
                elif cmd == "set_muted":
                    self.set_muted(bool(rec.get("muted")))
            ticks += 1
            # ~20 Hz meters for visualizer; full status ~2s
            self._publish_meters()
            if ticks % 40 == 0:
                self._publish_status()
            await asyncio.sleep(0.05)

    async def run_until_stopped(self, seconds: Optional[float] = None) -> dict[str, Any]:
        ctrl = asyncio.create_task(self._control_loop())
        try:
            if seconds is None:
                await self._closed.wait()
            else:
                try:
                    await asyncio.wait_for(self._closed.wait(), timeout=seconds)
                except asyncio.TimeoutError:
                    _log(f"timeout {seconds}s")
        finally:
            self._stop_requested = True
            ctrl.cancel()
            try:
                await ctrl
            except (asyncio.CancelledError, Exception):
                pass
            await self.stop()
        return self.stats

    async def stop(self) -> None:
        if self.mic_track is not None:
            try:
                self.mic_track.stop()
            except Exception:
                pass
            self.mic_track = None
        if self.speaker is not None:
            try:
                self.speaker.stop()
            except Exception:
                pass
            self.speaker = None
        if self.pc is not None:
            try:
                await self.pc.close()
            except Exception:
                pass
            self.pc = None
        self._closed.set()
        stopped = {
            "status": "stopped",
            "session_name": self.session_name,
            "profile": self.profile.name,
            "voice": self.voice,
            "muted": self._muted,
            "injecting": False,
            "uplink_peak": 0.0,
            "downlink_peak": 0.0,
            "audio_injects": self.stats.get("audio_injects"),
        }
        write_live_status(stopped)
        write_meters(stopped)
        _log("session stopped")


async def run_live(
    profile_name: str = "default",
    instructions: str = "",
    *,
    use_mic: bool = True,
    seconds: Optional[float] = None,
    session_name: str = "default",
    muted: bool = False,
    context: str = "",
) -> dict[str, Any]:
    prof = load_profile(profile_name)
    if not instructions:
        instructions = prof.assemble_instructions(context)
    sess = LiveSession(
        prof,
        instructions,
        use_mic=use_mic,
        session_name=session_name,
        muted=muted,
        context=context,
    )
    await sess.start()
    return await sess.run_until_stopped(seconds=seconds)
