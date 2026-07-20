from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from .profiles import SessionProfile


def build_voice_session_payload(
    profile: SessionProfile,
    *,
    voice_session_id: str | None = None,
    timezone: str = "Europe/Moscow",
    timezone_offset_min: int | None = None,
    voice: str | None = None,
) -> dict[str, Any]:
    """Multipart `session` field for POST /realtime/wm (from HAR)."""
    from .voices import normalize_voice

    vid = voice_session_id or str(uuid.uuid4()).upper()
    if timezone_offset_min is None:
        try:
            off = datetime.now(ZoneInfo(timezone)).utcoffset()
            timezone_offset_min = int(-off.total_seconds() // 60) if off else 0
        except Exception:
            timezone_offset_min = 0

    voice_id = normalize_voice(voice if voice is not None else profile.voice)

    return {
        "backend_reasoning_effort": "instant",
        "language_code": "auto",
        "requested_default_model": "",
        "voice": voice_id,
        "voice_session_id": vid,
        "voice_status_request_id": vid,
        "timezone_offset_min": timezone_offset_min,
        "timezone": timezone,
        "voice_mode": profile.voice_mode,
        "model_slug": "",
        "model_slug_advanced": "",
        "client_tools": [],
        "history_and_training_disabled": False,
        "conversation_mode": {"kind": "primary_assistant"},
        "enable_message_streaming": True,
    }


# Soft cap per plain-text DC message (Wingman is not Realtime; keep entries small)
PLAIN_ENTRY_MAX = 4000


def _clip_plain(text: str, limit: int = PLAIN_ENTRY_MAX) -> str:
    t = (text or "").strip()
    if len(t) <= limit:
        return t
    return t[:limit] + "\n…[truncated]"


def plain_boot_entries(instructions: str, context: str = "") -> list[str]:
    """Exactly one plain-text DC inject for call start (product path).

    Single compact: header + assembled instructions (profile + context pack).
    Mid-call top-ups stay separate via plain_topup_entry. No JSON envelope.
    """
    ins = (instructions or "").strip()
    ctx = (context or "").strip()
    header = (
        "[BTW-VC SESSION BRIEF — binding for this voice call]\n"
        "You are the /btw-vc side channel for a Grok Build coding session. "
        "Grok codes; you only advise. You cannot edit files.\n"
    )
    if ins:
        body = header + "\n" + ins
    elif ctx:
        body = header + "\n## Current Grok session context\n" + ctx
    else:
        body = header.strip()
    return [_clip_plain(body)]


def plain_topup_entry(delta: str) -> str:
    """Single plain-text DC entry for mid-call context top-up."""
    d = (delta or "").strip()
    if not d:
        return ""
    return _clip_plain(
        "[BTW-VC CONTEXT UPDATE — treat as current Grok session facts]\n" + d
    )


def instruction_events(instructions: str) -> list[dict[str, Any]]:
    """Legacy Realtime-style DC JSON (opt-in only — often kills Wingman PC).

    Prefer plain_boot_entries(). Enable with BTW_DC_REALTIME=1.
    """
    text = (instructions or "").strip()
    if not text:
        return []
    if len(text) > 12000:
        text = text[:12000] + "\n…[truncated]"

    bootstrap = (
        "[BTW-VC SESSION BRIEF — binding for this voice call]\n"
        "You are the /btw-vc side channel for a Grok Build coding session. "
        "Follow the system rules and context below. Do not claim you can edit files.\n\n"
        + text
    )

    return [
        {
            "type": "session.update",
            "session": {
                "instructions": text,
                "modalities": ["audio", "text"],
            },
        },
        {
            "type": "session.update",
            "session": {
                "type": "realtime",
                "instructions": text,
                "modalities": ["audio", "text"],
            },
        },
        {
            "type": "conversation.item.create",
            "item": {
                "type": "message",
                "role": "system",
                "content": [{"type": "input_text", "text": text}],
            },
        },
        {
            "type": "conversation.item.create",
            "item": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": bootstrap}],
            },
        },
        {"type": "response.create"},
    ]


def context_push_events(context: str) -> list[dict[str, Any]]:
    """Legacy Realtime-style mid-call JSON (opt-in BTW_DC_REALTIME=1)."""
    ctx = (context or "").strip()
    if not ctx:
        return []
    if len(ctx) > 8000:
        ctx = ctx[:8000] + "\n…[truncated]"
    msg = (
        "[BTW-VC CONTEXT UPDATE — treat as current Grok session facts]\n" + ctx
    )
    return [
        {
            "type": "conversation.item.create",
            "item": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": msg}],
            },
        },
        {"type": "response.create"},
    ]
