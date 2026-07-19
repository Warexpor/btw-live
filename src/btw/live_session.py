"""Standalone Live session: mint + aiortc + local audio + control IPC."""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any, Callable, Optional

from aiortc import RTCPeerConnection, RTCSessionDescription

from .audio_io import MicrophoneTrack, SilentTrack, SpeakerPlayer
from .control import drain_commands, write_live_status
from .http_client import ChatGPTClient
from .profiles import SessionProfile, load_profile
from .session_json import (
    build_voice_session_payload,
    context_push_events,
    instruction_events,
)

log = logging.getLogger("btw.live")


def _log(msg: str) -> None:
    log.info(msg)
    print(msg, flush=True)


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
    ):
        self.profile = profile
        self.instructions = instructions
        self.use_mic = use_mic
        self.use_speaker = use_speaker
        self.session_name = session_name
        self.voice = voice or profile.voice
        self.on_dc_message = on_dc_message
        self.client = ChatGPTClient()
        self.pc: Optional[RTCPeerConnection] = None
        self.speaker: Optional[SpeakerPlayer] = None
        self.mic_track = None
        self.voice_session_id = str(uuid.uuid4()).upper()
        self.stats: dict[str, Any] = {}
        self._dc = None
        self._closed = asyncio.Event()
        self._muted = bool(muted)
        self._stop_requested = False

    def set_muted(self, muted: bool) -> None:
        self._muted = bool(muted)
        if self.mic_track is not None and hasattr(self.mic_track, "set_muted"):
            self.mic_track.set_muted(self._muted)
        self.stats["muted"] = self._muted
        _log(f"mic muted={self._muted}")
        self._publish_status()

    def _publish_status(self) -> None:
        write_live_status(
            {
                "status": "live" if self.pc and not self._closed.is_set() else "idle",
                "session_name": self.session_name,
                "profile": self.profile.name,
                "voice": self.voice,
                "voice_session_id": self.voice_session_id,
                "muted": self._muted,
                "pc": self.stats.get("pc_state"),
                "ice": self.stats.get("ice_state"),
                "mic": self.stats.get("mic"),
                "instructions_chars": len(self.instructions or ""),
            }
        )

    def _send_events(self, channel, events: list[dict[str, Any]], tag: str) -> int:
        n = 0
        for ev in events:
            try:
                channel.send(json.dumps(ev))
                self.stats.setdefault("dc_events", []).append(ev.get("type"))
                _log(f"dc_send[{tag}] {ev.get('type')}")
                n += 1
            except Exception as e:
                _log(f"dc_send err: {e}")
        return n

    def _send_instructions(self, channel) -> None:
        self._send_events(channel, instruction_events(self.instructions), "boot")

    def reinject_instructions(self, instructions: str | None = None) -> bool:
        if instructions is not None:
            self.instructions = instructions
        ch = self._dc
        if not ch or getattr(ch, "readyState", None) != "open":
            _log("reinject: no open datachannel")
            return False
        self._send_events(ch, instruction_events(self.instructions), "reinject")
        return True

    def push_context_live(self, context: str) -> bool:
        ch = self._dc
        if not ch or getattr(ch, "readyState", None) != "open":
            _log("push_context_live: no open datachannel — stored for next reinject only")
            return False
        self._send_events(ch, context_push_events(context), "context")
        return True

    async def start(self) -> dict[str, Any]:
        _log(f"auth backend={self.client.backend} …")
        token = self.client.fetch_access_token()
        _log(f"accessToken ok len={len(token)}")

        pc = RTCPeerConnection()
        self.pc = pc
        self.stats["ice"] = []
        self.stats["dc_events"] = []
        self.stats["muted"] = self._muted

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
                self._send_instructions(channel)
                self._publish_status()

            @channel.on("message")
            def on_message(message):
                text = message if isinstance(message, str) else repr(message)[:500]
                self.stats.setdefault("dc_msgs", []).append(text[:500])
                _log(f"dc_msg {text[:200]}")
                if self.on_dc_message:
                    try:
                        self.on_dc_message(text)
                    except Exception:
                        pass

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

        if self.use_mic:
            try:
                self.mic_track = MicrophoneTrack()
                if self._muted:
                    self.mic_track.set_muted(True)
                pc.addTrack(self.mic_track)
                self.stats["mic"] = "microphone"
                _log("mic: MicrophoneTrack")
            except Exception as e:
                _log(f"mic failed ({e}); silent uplink")
                self.mic_track = SilentTrack()
                pc.addTrack(self.mic_track)
                self.stats["mic"] = "silent"
        else:
            self.mic_track = SilentTrack()
            pc.addTrack(self.mic_track)
            self.stats["mic"] = "silent"

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
                elif cmd == "reinject":
                    self.reinject_instructions(rec.get("instructions"))
                elif cmd == "push_context":
                    ctx = rec.get("context") or ""
                    self.push_context_live(ctx)
                elif cmd == "set_muted":
                    self.set_muted(bool(rec.get("muted")))
            await asyncio.sleep(0.25)

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
            except Exception:
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
        write_live_status({"status": "stopped", "session_name": self.session_name})
        _log("session stopped")


async def run_live(
    profile_name: str = "default",
    instructions: str = "",
    *,
    use_mic: bool = True,
    seconds: Optional[float] = None,
    session_name: str = "default",
    muted: bool = False,
) -> dict[str, Any]:
    prof = load_profile(profile_name)
    if not instructions:
        instructions = prof.assemble_instructions("")
    sess = LiveSession(
        prof,
        instructions,
        use_mic=use_mic,
        session_name=session_name,
        muted=muted,
    )
    await sess.start()
    return await sess.run_until_stopped(seconds=seconds)
