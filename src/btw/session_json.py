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
    conversation_id: str | None = None,
    bind_conversation: bool = True,
) -> dict[str, Any]:
    """Multipart `session` field for POST /realtime/wm (from HAR).

    When conversation_id is set (and bind_conversation), attach defensive
    bind fields so Live may rejoin the ChatGPT backend thread.
    """
    import os

    from .voices import normalize_voice

    vid = voice_session_id or str(uuid.uuid4()).upper()
    if timezone_offset_min is None:
        try:
            off = datetime.now(ZoneInfo(timezone)).utcoffset()
            timezone_offset_min = int(-off.total_seconds() // 60) if off else 0
        except Exception:
            timezone_offset_min = 0

    voice_id = normalize_voice(voice if voice is not None else profile.voice)

    mode: dict[str, Any] = {"kind": "primary_assistant"}
    payload: dict[str, Any] = {
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
        "conversation_mode": mode,
        "enable_message_streaming": True,
    }

    env_off = os.environ.get("BTW_NO_CONVERSATION_BIND", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    cid = (conversation_id or "").strip()
    if cid and bind_conversation and not env_off:
        payload["conversation_id"] = cid
        mode["conversation_id"] = cid
        mode["id"] = cid

    return payload


# Soft caps — brief enough for DC, enough for full agent picture
PLAIN_ENTRY_MAX = 4000  # hard ceiling (compat)
PLAIN_BOOT_MAX = 6400  # one boot message after VC init (match spoken budget / 2 min)
PLAIN_TOPUP_MAX = 1200  # one mid-call "what's new" message


def _normalize_snip(text: str) -> str:
    """Collapse noise; keep newlines for structure."""
    t = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not t:
        return ""
    lines = []
    blank = False
    for line in t.split("\n"):
        s = " ".join(line.split())
        if not s:
            if not blank:
                lines.append("")
            blank = True
            continue
        blank = False
        lines.append(s)
    return "\n".join(lines).strip()


def _clip_plain(text: str, limit: int = PLAIN_ENTRY_MAX) -> str:
    t = _normalize_snip(text)
    if len(t) <= limit:
        return t
    # Prefer cut at last newline / sentence in the window
    window = t[: max(0, limit - 14)]
    cut = max(window.rfind("\n"), window.rfind(". "), window.rfind("; "))
    if cut < limit // 3:
        cut = len(window)
    return window[:cut].rstrip() + "\n…[truncated]"


def plain_boot_message(instructions: str, context: str = "") -> str:
    """Exactly one plain-text DC payload for call start (best-effort only).

    Product inject is uplink TTS (`spoken_bootstrap`). This string is still
    sent on open DC when possible. Brief structured UTF-8 — not multi-frame.
    Prefers compact role + session context pack over dumping a huge assemble.
    """
    ins = _normalize_snip(instructions)
    ctx = _normalize_snip(context)

    header = (
        "[BTW-VC SESSION BRIEF]\n"
        "Voice advisor for Grok Build. Grok codes; you only advise. "
        "Cannot edit files. Treat facts below as ground truth.\n"
    )

    # Prefer raw context pack (session picture). Fall back to assembled instructions.
    if ctx:
        body = header + "\n## Session facts\n" + ctx
        # If instructions add unique system lines not already in ctx, append a short tail
        if ins and ctx not in ins:
            # Keep only non-duplicate role lines short — skip full re-paste of ctx
            pass
    elif ins:
        body = header + "\n" + ins
    else:
        body = header.rstrip()

    return _clip_plain(body, PLAIN_BOOT_MAX)


def plain_boot_entries(instructions: str, context: str = "") -> list[str]:
    """Compat: always a one-element list around plain_boot_message()."""
    msg = plain_boot_message(instructions, context)
    return [msg] if msg else []


def plain_topup_message(delta: str) -> str:
    """Exactly one plain-text DC payload for mid-call top-up (best-effort only).

    Product top-up is uplink TTS (`spoken_topup`). This is a single structured
    UTF-8 string for one channel.send when DC is still open. Delta only.
    """
    d = _normalize_snip(delta)
    if not d:
        return ""
    body = (
        "[BTW-VC WHAT'S NEW]\n"
        "Mid-call update. Merge into prior session facts; do not drop earlier context.\n\n"
        + d
    )
    return _clip_plain(body, PLAIN_TOPUP_MAX)


def plain_topup_entry(delta: str) -> str:
    """Compat alias for plain_topup_message()."""
    return plain_topup_message(delta)


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
