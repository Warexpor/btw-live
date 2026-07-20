"""Standalone Live session: mint + aiortc + local audio + control IPC.

Context delivery (product — 0.5.36+):
  Wingman only reliably hears the **audio uplink**. Plain DC is best-effort
  (channel often closes in <100ms; agent does not treat plain UTF-8 as context).

  - Boot / top-up primary: short SAPI TTS on the mic uplink (default ON)
  - Disable: BTW_NO_AUDIO_INJECT=1 (or BTW_AUDIO_BOOT=0 / BTW_AUDIO_TOPUP=0)
  - DC plain still attempted if channel open (not sufficient alone)
  - Primary DC: oai-events (BTW_DC_NEGOTIATED=1 for experimental id=0)
  - Realtime multi-JSON only if BTW_DC_REALTIME=1 (often kills PC)
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
    plain_boot_message,
    plain_topup_message,
)

log = logging.getLogger("btw.live")

# Spoken inject caps — product path is uplink TTS (DC ignored by Wingman).
# Keep under INJECT_MAX_SAMPLES (~120s); denser pack still fits in one brief.
AUDIO_BRIEF_MAX = 6400  # ~2 min of SAPI room for real session pack
AUDIO_TOPUP_MAX = 1200
# No artificial settle after PC connect (speak as soon as connected)
AUDIO_BOOT_SETTLE_S = 0.0

# Product DC label for standalone mint (stable multi-minute sessions).
DC_LABEL = "oai-events"
# Browser Wingman uses createDataChannel("", {negotiated:true, id:0}) — but that
# SDP shape makes /realtime/wm close the PeerConnection under aiortc (0 frames).
# Keep constant for opt-in experiments only (BTW_DC_NEGOTIATED=1).
DC_NEGOTIATED_ID = 0
# Deferred path only (BTW_DC_DEFER_BOOT=1): wait inbound or this timeout
BOOT_INJECT_WAIT_S = 0.4
BOOT_INJECT_SETTLE_S = 0.0
# One retry if first send returned 0 while channel still open
BOOT_INJECT_RETRY_S = 0.08


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


def _speech_normalize(text: str) -> str:
    """Make pack text speakable: strip markdown chrome, keep facts."""
    t = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    lines: list[str] = []
    for raw in t.split("\n"):
        s = raw.strip()
        if not s:
            continue
        # drop pure markdown decoration
        if s.startswith("#"):
            s = s.lstrip("#").strip()
        if s.startswith("```") or s in ("---", "***", "___"):
            continue
        s = s.replace("**", "").replace("__", "").replace("`", "")
        s = " ".join(s.split())
        if s:
            lines.append(s)
    # Join with period-space so ASR gets complete clauses, not one giant run-on
    out = ". ".join(lines)
    out = out.replace("..", ".").replace(" .", ".")
    return out.strip(" .")


def spoken_bootstrap(
    instructions: str,
    context: str = "",
    *,
    resume_snip: str = "",
) -> str:
    """Full spoken session brief for call start (product inject path).

    Prefers the session context pack; falls back to assembled instructions.
    When resume_snip is set (ChatGPT conversation hydrate), prior voice turns
    are spoken first so the model continues that thread's facts.
    """
    ctx = _speech_normalize(context)
    ins = _speech_normalize(instructions)
    resume = _speech_normalize(resume_snip)
    # Prefer pack; if instructions are much richer, use them
    if ctx and ins and len(ins) > len(ctx) * 1.4 and ctx not in ins:
        body = ins
    else:
        body = ctx or ins
    # Budget: leave room for resume when present
    resume_budget = min(1200, AUDIO_BRIEF_MAX // 2) if resume else 0
    body_budget = AUDIO_BRIEF_MAX - resume_budget - 80
    body = _clip(body, max(400, body_budget))
    if resume:
        resume = _clip(resume, resume_budget)
    role = (
        "Binding session brief for this voice call. "
        "You are the voice advisor for a Grok Build coding session. "
        "Grok implements code; you only advise. "
        "You cannot edit files or run tools. "
        "Treat the following as ground truth for this call"
    )
    parts = [role]
    if resume:
        parts.append(
            "Prior voice turns from this ChatGPT conversation — continue from them"
        )
        parts.append(resume)
    if body:
        parts.append("Current Grok session facts")
        parts.append(body)
    elif not resume:
        parts.append("Wait for the user")
    return ". ".join(parts)


def spoken_topup(delta: str) -> str:
    """Spoken mid-call top-up: what's new only, enough detail to merge."""
    d = _speech_normalize(delta)
    d = _clip(d, AUDIO_TOPUP_MAX)
    if not d:
        return ""
    return (
        "Mid-call context update. Merge these new facts into the session; "
        "do not drop earlier facts. "
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
        conversation_id: str = "",
        resume_snip: str = "",
        voice_session_id: str | None = None,
    ):
        self.profile = profile
        self.instructions = instructions
        self.context = context or ""
        self.conversation_id = (conversation_id or "").strip()
        self.resume_snip = resume_snip or ""
        self.use_mic = use_mic
        self.use_speaker = use_speaker
        self.session_name = session_name
        self.voice = voice or profile.voice
        self.on_dc_message = on_dc_message
        self.client = ChatGPTClient()
        self.pc: Optional[RTCPeerConnection] = None
        self.speaker: Optional[SpeakerPlayer] = None
        self.mic_track: Optional[InjectableUplinkTrack] = None
        # New Live leg UUID by default; conversation_id is the long-lived thread
        self.voice_session_id = (voice_session_id or str(uuid.uuid4())).upper()
        self.stats: dict[str, Any] = {}
        self._dc = None
        self._closed = asyncio.Event()
        self._muted = bool(muted)
        self._stop_requested = False
        self._inbox_path = data_dir() / "dc_inbox.jsonl"
        self._boot_inject_done = False
        self._boot_inject_task: Optional[asyncio.Task] = None
        self._audio_boot_done = False
        self._audio_boot_task: Optional[asyncio.Task] = None
        self._dc_first_inbound = asyncio.Event()
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def set_muted(self, muted: bool) -> None:
        self._muted = bool(muted)
        if self.mic_track is not None:
            self.mic_track.set_muted(self._muted)
        self.stats["muted"] = self._muted
        _log(f"mic muted={self._muted}")
        self._publish_status()

    def _meter_snapshot(self) -> dict[str, Any]:
        # last_peak is an attack/release envelope on real audio frames (not raw sample spikes)
        up = (
            float(getattr(self.mic_track, "last_peak", 0.0) or 0.0)
            if self.mic_track
            else 0.0
        )
        down = 0.0
        sp_stats: dict[str, Any] = {}
        if self.speaker is not None:
            # sample_meter releases when remote audio stops (no side-effect decay race)
            sample = getattr(self.speaker, "sample_meter", None)
            if callable(sample):
                down = float(sample() or 0.0)
            else:
                down = float(getattr(self.speaker, "last_peak", 0.0) or 0.0)
            st = getattr(self.speaker, "stats", None)
            if callable(st):
                try:
                    sp_stats = dict(st() or {})
                except Exception:
                    sp_stats = {}
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
            "uplink_peak": min(1.0, max(0.0, up)),
            "downlink_peak": min(1.0, max(0.0, down)),
            "uplink_src": uplink_src,
            "mic_frames": mic_frames,
            "speaker_underruns": int(sp_stats.get("underruns") or 0),
            "speaker_partial_underruns": int(sp_stats.get("partial_underruns") or 0),
            "speaker_ring_drops": int(sp_stats.get("ring_drops") or 0),
            "speaker_sd_underflows": int(sp_stats.get("sd_underflows") or 0),
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

    def _audio_inject_enabled(self) -> bool:
        """Product default ON — wingman only reliably consumes uplink audio."""
        if self._env_flag("BTW_NO_AUDIO_INJECT"):
            return False
        # Explicit disable of either legacy flag turns audio inject off
        for name in ("BTW_AUDIO_BOOT", "BTW_AUDIO_TOPUP"):
            raw = os.environ.get(name)
            if raw is not None and raw.strip().lower() in ("0", "false", "no"):
                return False
        return True

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

    def _send_plain_one(self, channel, text: str, tag: str) -> bool:
        """Send exactly one plain UTF-8 string on the datachannel. Returns True if sent."""
        t = (text or "").strip()
        if not t:
            return False
        try:
            channel.send(t)
            self.stats.setdefault("dc_events", []).append("plain_text")
            self._append_inbox("out", t, {"tag": tag, "type": "plain_text", "i": 0})
            _log(f"dc_plain[{tag}] chars={len(t)} (single message)")
            return True
        except Exception as e:
            _log(f"dc_plain err: {e}")
            return False

    def _send_plain_texts(self, channel, texts: list[str], tag: str) -> int:
        """Send plain strings (top-up / reinject). Prefer one element."""
        n = 0
        for i, text in enumerate(texts):
            if self._send_plain_one(channel, text, f"{tag}:{i}" if i else tag):
                n += 1
        return n

    def _boot_inject_sync(self, channel, *, tag: str = "boot") -> int:
        """After VC init: send exactly ONE plain structured brief (or Realtime if forced).

        Product path never multi-sends. Returns 1 if the single message went out, else 0.
        """
        if self._boot_inject_done:
            _log(f"boot_inject skip: already sent tag={tag}")
            return 0
        try:
            if getattr(channel, "readyState", None) != "open":
                _log(f"boot_inject skip: readyState={getattr(channel, 'readyState', '?')}")
                return 0
            if self._env_flag("BTW_DC_REALTIME"):
                # Dev-only multi-JSON path — not product
                n = self._send_events(
                    channel, instruction_events(self.instructions), tag
                )
                self.stats["boot_events"] = n
                self.stats["dc_injection_sent"] = n > 0
                if n > 0:
                    self._boot_inject_done = True
                _log(
                    f"boot_dc realtime tag={tag} sent={n} "
                    f"ready={getattr(channel, 'readyState', '?')}"
                )
                return 1 if n > 0 else 0

            msg = plain_boot_message(self.instructions, self.context)
            if not msg:
                _log("boot_inject skip: empty plain_boot_message")
                return 0
            ok = self._send_plain_one(channel, msg, tag)
            self.stats["boot_events"] = 1 if ok else 0
            self.stats["dc_injection_sent"] = ok
            self.stats["boot_chars"] = len(msg) if ok else 0
            if ok:
                # Once sent, never send another boot message this call
                self._boot_inject_done = True
            _log(
                f"boot_dc plain tag={tag} ok={ok} chars={len(msg)} "
                f"ready={getattr(channel, 'readyState', '?')}"
            )
            return 1 if ok else 0
        except Exception as e:
            _log(f"boot_inject err: {e}")
            return 0

    def _arm_boot_inject(self, channel) -> None:
        """Send exactly one boot plain message. Default: immediate on open.

        Server often closes the DC within ~100ms with no inbound frames, so the
        deferred wait path never gets a send window. Opt-in defer: BTW_DC_DEFER_BOOT=1.
        """
        if self._boot_inject_done or self._boot_inject_task is not None:
            return
        if self._env_flag("BTW_DC_DEFER_BOOT"):
            loop = self._loop
            if loop is None:
                try:
                    loop = asyncio.get_running_loop()
                    self._loop = loop
                except RuntimeError:
                    _log("boot_inject arm: no loop — sync immediate")
                    self._boot_inject_sync(channel, tag="boot_sync")
                    return
            self._boot_inject_task = loop.create_task(
                self._deferred_boot_inject(channel), name="btw-boot-inject"
            )
            _log("boot_inject armed (deferred BTW_DC_DEFER_BOOT=1)")
            return
        # Product path: send now while readyState is still open.
        n = self._boot_inject_sync(channel, tag="boot_open")
        self.stats["boot_inject_reason"] = "open" if n > 0 else "open+failed"
        if n > 0:
            self._publish_status()
            return
        # Channel already closed or send failed — one short retry on loop if any.
        loop = self._loop
        if loop is None:
            try:
                loop = asyncio.get_running_loop()
                self._loop = loop
            except RuntimeError:
                return
        self._boot_inject_task = loop.create_task(
            self._boot_inject_retry_once(channel), name="btw-boot-retry"
        )

    async def _boot_inject_retry_once(self, channel) -> None:
        """Single delayed retry only if first open send returned 0. Never double-send."""
        if self._boot_inject_done or self._closed.is_set():
            return
        try:
            await asyncio.sleep(BOOT_INJECT_RETRY_S)
        except asyncio.CancelledError:
            return
        if self._boot_inject_done or self._closed.is_set():
            return
        ch = self._dc if self._dc is not None else channel
        if getattr(ch, "readyState", None) != "open":
            _log("boot_inject retry skip: channel not open")
            self.stats["boot_inject_reason"] = "open+failed"
            self._publish_status()
            return
        n = self._boot_inject_sync(ch, tag="boot_retry")
        self.stats["boot_inject_reason"] = "open+retry" if n > 0 else "open+failed"
        self._publish_status()

    async def _deferred_boot_inject(self, channel) -> None:
        """BTW_DC_DEFER_BOOT only: wait inbound/timeout then one plain brief."""
        if self._boot_inject_done or self._closed.is_set():
            return
        reason = "timeout"
        try:
            await asyncio.wait_for(
                self._dc_first_inbound.wait(), timeout=BOOT_INJECT_WAIT_S
            )
            reason = "first_inbound"
            await asyncio.sleep(BOOT_INJECT_SETTLE_S)
        except asyncio.TimeoutError:
            pass
        except asyncio.CancelledError:
            return

        if self._boot_inject_done or self._closed.is_set():
            return

        for _ in range(20):
            ice = None
            if self.pc is not None:
                ice = getattr(self.pc, "iceConnectionState", None)
            if ice in ("connected", "completed", None):
                break
            if ice in ("failed", "closed"):
                _log(f"boot_inject abort ice={ice}")
                return
            await asyncio.sleep(0.05)

        n = self._boot_inject_sync(channel, tag=f"boot_{reason}")
        if n > 0:
            self.stats["boot_inject_reason"] = reason
            self._publish_status()
            return

        _log(f"boot_inject retry in {BOOT_INJECT_RETRY_S}s (first sent nothing)")
        try:
            await asyncio.sleep(BOOT_INJECT_RETRY_S)
        except asyncio.CancelledError:
            return
        if self._boot_inject_done or self._closed.is_set():
            return
        ch = self._dc if self._dc is not None else channel
        if getattr(ch, "readyState", None) != "open":
            _log("boot_inject retry skip: channel not open")
            self.stats["boot_inject_reason"] = f"{reason}+failed"
            self._publish_status()
            return
        n2 = self._boot_inject_sync(ch, tag="boot_retry")
        self.stats["boot_inject_reason"] = (
            f"{reason}+retry" if n2 > 0 else f"{reason}+failed"
        )
        self._publish_status()

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
        """Queue spoken session brief on the uplink (product primary inject)."""
        if not self._audio_inject_enabled():
            _log("audio bootstrap skipped (BTW_NO_AUDIO_INJECT or AUDIO_*=0)")
            self.stats["bootstrap"] = False
            return False
        ok = self.speak_text(
            spoken_bootstrap(
                self.instructions,
                self.context,
                resume_snip=self.resume_snip,
            ),
            tag="bootstrap",
        )
        self.stats["bootstrap"] = ok
        self.stats["resume_chars"] = len(self.resume_snip or "")
        if ok:
            self._audio_boot_done = True
        return ok

    def speak_context_topup(self, delta: str) -> bool:
        if not self._audio_inject_enabled():
            _log("audio topup skipped (BTW_NO_AUDIO_INJECT or AUDIO_*=0)")
            return False
        return self.speak_text(spoken_topup(delta), tag="topup")

    def _arm_audio_boot(self) -> None:
        """Speak brief after media is up — default product inject path."""
        if self._audio_boot_done or self._audio_boot_task is not None:
            return
        if not self._audio_inject_enabled():
            self.stats["bootstrap"] = False
            _log("audio boot not armed (disabled)")
            return
        loop = self._loop
        if loop is None:
            try:
                loop = asyncio.get_running_loop()
                self._loop = loop
            except RuntimeError:
                _log("audio boot arm: no loop — sync speak")
                self.speak_bootstrap()
                return
        self._audio_boot_task = loop.create_task(
            self._audio_boot_when_live(), name="btw-audio-boot"
        )
        _log("audio boot armed (speak after PC connected)")

    async def _audio_boot_when_live(self) -> None:
        """Wait for connected media, then one uplink TTS brief."""
        if self._audio_boot_done or self._closed.is_set():
            return
        try:
            for _ in range(120):  # ~6s
                if self._closed.is_set():
                    return
                st = getattr(self.pc, "connectionState", None) if self.pc else None
                if st == "connected":
                    break
                await asyncio.sleep(0.05)
            else:
                _log("audio boot: PC never connected — speaking anyway")
            if AUDIO_BOOT_SETTLE_S > 0:
                await asyncio.sleep(AUDIO_BOOT_SETTLE_S)
        except asyncio.CancelledError:
            return
        if self._audio_boot_done or self._closed.is_set():
            return
        # Run blocking SAPI off the event loop
        try:
            ok = await asyncio.to_thread(
                self.speak_text,
                spoken_bootstrap(
                    self.instructions,
                    self.context,
                    resume_snip=self.resume_snip,
                ),
                tag="bootstrap",
            )
        except Exception as e:
            _log(f"audio boot err: {e}")
            ok = False
        self.stats["bootstrap"] = bool(ok)
        self.stats["resume_chars"] = len(self.resume_snip or "")
        if ok:
            self._audio_boot_done = True
            _log(
                f"audio boot delivered on uplink resume_chars={self.stats['resume_chars']}"
            )
        else:
            _log("audio boot failed")
        self._publish_status()

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
                self._send_plain_one(
                    ch,
                    plain_boot_message(self.instructions, self.context),
                    "reinject",
                )
            ok_dc = True
        else:
            _log("reinject: no open datachannel (audio path still used)")
        ok_audio = False
        if self._audio_inject_enabled():
            ok_audio = self.speak_text(
                spoken_bootstrap(self.instructions, self.context), tag="reinject"
            )
        return ok_audio or ok_dc

    def push_context_live(
        self, context_delta: str, *, full_context: str | None = None
    ) -> bool:
        """Mid-call top-up: pack update + uplink TTS (primary) + DC plain if open."""
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
                n = self._send_events(ch, context_push_events(delta), "context")
                ok_dc = n > 0
                self.stats["topup_events"] = n
            else:
                msg = plain_topup_message(delta)
                if msg:
                    ok_dc = self._send_plain_one(ch, msg, "topup")
                    self.stats["topup_events"] = 1 if ok_dc else 0
                    self.stats["topup_chars"] = len(msg) if ok_dc else 0
                    if ok_dc:
                        _log(f"topup_dc plain ok chars={len(msg)} (best-effort)")
        elif delta:
            _log("push_context: DC closed — using audio uplink")

        ok_audio = self.speak_context_topup(delta) if delta else False
        if ok_audio:
            _log(f"topup_audio ok chars={len(delta)}")
        self._publish_status()
        return ok_audio or ok_dc

    def _handle_dc_message(self, message: Any, label: str) -> None:
        text = _dc_to_text(message)
        self.stats.setdefault("dc_msgs", []).append(text[:500])
        self._append_inbox("in", text, {"label": label})
        _log(f"dc_msg[{label}] {text[:200]}")
        if not self._dc_first_inbound.is_set():
            self._dc_first_inbound.set()
        if self.on_dc_message:
            try:
                self.on_dc_message(text)
            except Exception:
                pass

    async def start(self) -> dict[str, Any]:
        # Drop stop/mute orphans from a prior kill or ESC key-repeat so this
        # session does not die on the first control tick.
        clear_commands()
        self._loop = asyncio.get_running_loop()
        self._boot_inject_done = False
        self._boot_inject_task = None
        self._audio_boot_done = False
        self._audio_boot_task = None
        self._dc_first_inbound = asyncio.Event()
        try:
            from .proxy import proxy_info

            pi = proxy_info()
            _log(
                f"proxy http={pi.get('url') or 'direct'} "
                f"(media=WebRTC direct unless OS TUN)"
            )
        except Exception as e:
            _log(f"proxy info err: {e}")
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
                                st = speaker.stats() if hasattr(speaker, "stats") else {}
                                _log(
                                    f"speaker: frames={frames_n} "
                                    f"u={st.get('underruns', 0)} "
                                    f"su={st.get('silence_underruns', 0)} "
                                    f"pu={st.get('partial_underruns', 0)} "
                                    f"drop={st.get('ring_drops', 0)} "
                                    f"sd_uf={st.get('sd_underflows', 0)} "
                                    f"rb={st.get('rebuffers', 0)} "
                                    f"tgt={st.get('target', 0)} "
                                    f"ring={st.get('ring', 0)}"
                                )
                        except Exception as e:
                            _log(f"play loop end frames={frames_n}: {e}")
                            break

                asyncio.ensure_future(_play())

        def wire_dc(channel, label: str, *, primary: bool = False):
            """Wire DC handlers. Boot inject only on primary channel."""
            ch_id = getattr(channel, "id", None)
            _log(
                f"dc wire {label} label={channel.label!r} id={ch_id} "
                f"primary={primary}"
            )

            @channel.on("open")
            def on_open():
                _log(f"dc_open {label} id={getattr(channel, 'id', None)}")
                if primary or self._dc is None:
                    self._dc = channel
                self.stats["dc_open"] = True
                self.stats["dc_label"] = getattr(channel, "label", "") or ""
                self.stats["dc_id"] = getattr(channel, "id", None)
                if primary:
                    self._arm_boot_inject(channel)
                self._publish_status()

            @channel.on("message")
            def on_message(message):
                if primary or self._dc is channel:
                    self._dc = channel
                self._handle_dc_message(message, label)

            @channel.on("close")
            def on_close():
                # Plain inject often closes the DC; audio PC can stay live.
                _log(f"dc_close {label} id={getattr(channel, 'id', None)}")
                if self._dc is channel:
                    self.stats["dc_open"] = False
                self._publish_status()

            if primary:
                self._dc = channel

        @pc.on("datachannel")
        def on_datachannel(channel):
            wire_dc(channel, "remote", primary=False)

        # Default: named oai-events. Negotiated empty id=0 kills this mint path
        # under aiortc (PC closed at 0 speaker frames) — only if explicitly forced.
        try:
            if self._env_flag("BTW_DC_NEGOTIATED"):
                local_dc = pc.createDataChannel(
                    "",
                    negotiated=True,
                    id=DC_NEGOTIATED_ID,
                )
                wire_dc(local_dc, "local-n0", primary=True)
                _log(
                    f"dc negotiated id={DC_NEGOTIATED_ID} label={local_dc.label!r} "
                    f"(BTW_DC_NEGOTIATED=1 — experimental)"
                )
            else:
                local_dc = pc.createDataChannel(DC_LABEL)
                wire_dc(local_dc, "local", primary=True)
                _log(f"dc label={DC_LABEL!r} id={getattr(local_dc, 'id', None)}")
        except Exception as e:
            _log(f"createDataChannel primary failed: {e}; fallback {DC_LABEL}")
            try:
                local_dc = pc.createDataChannel(DC_LABEL)
                wire_dc(local_dc, "local-fallback", primary=True)
            except Exception as e2:
                _log(f"createDataChannel failed: {e2}")

        base = None
        if self.use_mic:
            try:
                # paced=False: InjectableUplinkTrack owns the 20ms clock.
                # Double pacing caused delayed utterance dumps (no barge-in).
                base = MicrophoneTrack(paced=False)
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
        # Do not block mint on SAPI — arm after PC is connected (product inject).
        self.stats["bootstrap"] = False

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
            conversation_id=self.conversation_id or None,
        )
        _log(
            f"mint offer_sdp_len={len(sdp_offer)} voice={session.get('voice')} "
            f"conversation_id={session.get('conversation_id') or '-'}"
        )
        try:
            answer_sdp = self.client.mint_realtime(sdp_offer, session)
        except RuntimeError as e:
            # Bind fields may 4xx — retry unbound mint, keep hydrate resume_snip
            if self.conversation_id and "conversation_id" in session:
                _log(f"mint with conversation bind failed, retry unbound: {e}")
                session = build_voice_session_payload(
                    self.profile,
                    voice_session_id=self.voice_session_id,
                    voice=self.voice,
                    conversation_id=None,
                    bind_conversation=False,
                )
                answer_sdp = self.client.mint_realtime(sdp_offer, session)
                self.stats["mint_bind"] = "retry_unbound"
            else:
                raise
        else:
            self.stats["mint_bind"] = (
                "bound" if session.get("conversation_id") else "none"
            )
        _log(f"mint ok answer_sdp_len={len(answer_sdp)} bind={self.stats.get('mint_bind')}")
        self.stats["mint"] = 201
        self.stats["answer_len"] = len(answer_sdp)
        self.stats["conversation_id"] = self.conversation_id or None

        await pc.setRemoteDescription(
            RTCSessionDescription(sdp=answer_sdp, type="answer")
        )
        self.stats["voice_session_id"] = self.voice_session_id
        self.stats["ok"] = True
        try:
            from . import sessions_store as ss

            ss.set_last_voice_session(self.voice_session_id)
        except Exception as e:
            _log(f"persist last_voice_session_id err: {e}")
        self._arm_audio_boot()
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
                    # SAPI is blocking — keep control/meters loop responsive
                    await asyncio.to_thread(
                        self.push_context_live, delta, full_context=full
                    )
                elif cmd == "set_muted":
                    self.set_muted(bool(rec.get("muted")))
            ticks += 1
            # ~10 Hz meters (disk write); full status ~2s — high-rate JSON I/O
            # was competing with the audio callback under load.
            if ticks % 2 == 0:
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
        for attr in ("_boot_inject_task", "_audio_boot_task"):
            task = getattr(self, attr, None)
            if task is not None and not task.done():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
            setattr(self, attr, None)
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
            # call ended — don't leave mute sticky on the idle surface
            "muted": False,
            "injecting": False,
            "uplink_peak": 0.0,
            "downlink_peak": 0.0,
            "audio_injects": self.stats.get("audio_injects"),
        }
        write_live_status(stopped)
        write_meters(stopped)
        # Best-effort: auto-bind conversation if we only have voice_session_id
        try:
            await asyncio.to_thread(self._try_discover_conversation)
        except Exception as e:
            _log(f"conversation discover err: {e}")
        _log("session stopped")

    def _try_discover_conversation(self) -> None:
        """If unbound, search recent ChatGPT threads for this Live leg's voice id."""
        from . import sessions_store as ss

        active = ss.get_active()
        if (active.conversation_id or "").strip():
            return
        vid = self.voice_session_id
        if not vid:
            return
        try:
            found = self.client.find_conversation_by_voice_session(vid)
        except Exception as e:
            _log(f"find_conversation: {e}")
            return
        if not found:
            _log(f"discover: no conversation for voice_session_id={vid[:12]}…")
            return
        try:
            ss.bind_active_conversation(
                found,
                last_voice_session_id=vid,
            )
            self.conversation_id = found
            self.stats["conversation_id"] = found
            self.stats["discovered"] = True
            _log(f"discover: bound conversation_id={found}")
        except Exception as e:
            _log(f"discover bind err: {e}")


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
