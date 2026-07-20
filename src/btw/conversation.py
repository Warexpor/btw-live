"""ChatGPT backend conversation dump → voice turn resume snips."""
from __future__ import annotations

import base64
import json
import re
from typing import Any

# Match chatgpt.com conversation UUIDs (and similar)
_CONV_ID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)

RESUME_SNIP_MAX = 2200


def normalize_conversation_id(raw: str) -> str:
    """Extract/validate conversation id from uuid or chatgpt.com URL."""
    s = (raw or "").strip()
    if not s:
        raise ValueError("empty conversation_id")
    m = re.search(
        r"(?:/c/|/conversation/)([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-"
        r"[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})",
        s,
        re.I,
    )
    if m:
        s = m.group(1)
    elif re.search(r"chatgpt\.com", s, re.I):
        m2 = re.search(
            r"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
            r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12})",
            s,
            re.I,
        )
        if m2:
            s = m2.group(1)
    s = s.strip()
    if not _CONV_ID_RE.match(s):
        raise ValueError(f"invalid conversation_id: {raw!r}")
    return s


def decode_conversation_payload(raw: str | bytes | dict[str, Any]) -> dict[str, Any]:
    """Parse conversation GET body (JSON or base64-wrapped JSON as in HAR)."""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, bytes):
        text = raw.decode("utf-8", errors="replace")
    else:
        text = str(raw or "").strip()
    if not text:
        raise ValueError("empty conversation payload")
    if text.startswith("{") or text.startswith("["):
        data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError("conversation payload is not an object")
        return data
    # base64 (HAR content.encoding)
    pad = "=" * (-len(text) % 4)
    try:
        decoded = base64.b64decode(text + pad)
        data = json.loads(decoded.decode("utf-8"))
    except Exception as e:
        raise ValueError(f"cannot decode conversation payload: {e}") from e
    if not isinstance(data, dict):
        raise ValueError("decoded conversation payload is not an object")
    return data


def _part_text(part: Any) -> str:
    if part is None:
        return ""
    if isinstance(part, str):
        return part.strip()
    if isinstance(part, dict):
        if part.get("content_type") == "audio_transcription":
            return str(part.get("text") or "").strip()
        if "text" in part:
            return str(part.get("text") or "").strip()
    return ""


def _message_text(msg: dict[str, Any]) -> str:
    content = msg.get("content") or {}
    if not isinstance(content, dict):
        return ""
    parts = content.get("parts")
    if isinstance(parts, list):
        # Prefer audio_transcription when present
        texts: list[str] = []
        for p in parts:
            if isinstance(p, dict) and p.get("content_type") == "audio_transcription":
                t = _part_text(p)
                if t:
                    texts.append(t)
        if texts:
            return " ".join(texts).strip()
        for p in parts:
            t = _part_text(p)
            if t:
                texts.append(t)
        return " ".join(texts).strip()
    return ""


def extract_voice_turns(conv: dict[str, Any]) -> list[dict[str, Any]]:
    """Ordered user/assistant turns with text (voice ASR preferred)."""
    mapping = conv.get("mapping") or {}
    if not isinstance(mapping, dict):
        return []

    rows: list[dict[str, Any]] = []
    for mid, node in mapping.items():
        if not isinstance(node, dict):
            continue
        msg = node.get("message")
        if not isinstance(msg, dict):
            continue
        author = (msg.get("author") or {}).get("role") or ""
        if author not in ("user", "assistant"):
            continue
        text = _message_text(msg)
        if not text:
            continue
        meta = msg.get("metadata") or {}
        if not isinstance(meta, dict):
            meta = {}
        t = msg.get("create_time")
        try:
            t_f = float(t) if t is not None else 0.0
        except (TypeError, ValueError):
            t_f = 0.0
        rows.append(
            {
                "role": "you" if author == "user" else "ai",
                "text": text,
                "voice_session_id": str(meta.get("voice_session_id") or ""),
                "message_id": str(msg.get("id") or mid),
                "t": t_f,
                "voice_mode": bool(
                    meta.get("voice_mode_message")
                    or meta.get("bidi_voice_mode_message")
                ),
            }
        )

    rows.sort(key=lambda r: (r["t"], r["message_id"]))
    return rows


def find_current_node_parent(conv: dict[str, Any]) -> str | None:
    """Best-effort parent_message_id for prepare-style clients."""
    current = conv.get("current_node")
    mapping = conv.get("mapping") or {}
    if not current or not isinstance(mapping, dict):
        return None
    node = mapping.get(current) or {}
    if not isinstance(node, dict):
        return None
    parent = node.get("parent")
    if parent:
        return str(parent)
    msg = node.get("message") or {}
    if isinstance(msg, dict):
        mid = msg.get("id")
        if mid:
            return str(mid)
    return str(current) if current else None


def format_resume_snip(
    turns: list[dict[str, Any]],
    *,
    max_chars: int = RESUME_SNIP_MAX,
    voice_only: bool = False,
) -> str:
    """Recent-heavy you/ai transcript for spoken resume inject."""
    if not turns:
        return ""
    seq = turns
    if voice_only:
        voice_seq = [t for t in turns if t.get("voice_mode") or t.get("voice_session_id")]
        if voice_seq:
            seq = voice_seq

    lines = [f"{t['role']}: {t['text']}" for t in seq]
    # Prefer recent turns if over budget
    out_lines: list[str] = []
    total = 0
    for line in reversed(lines):
        # soft per-line clip
        if len(line) > 280:
            line = line[:277] + "…"
        add = len(line) + (1 if out_lines else 0)
        if total + add > max_chars and out_lines:
            break
        out_lines.append(line)
        total += add
    out_lines.reverse()
    body = "\n".join(out_lines)
    if len(lines) > len(out_lines):
        body = f"(earlier turns omitted)\n{body}"
    return body.strip()


def conversation_summary(conv: dict[str, Any]) -> dict[str, Any]:
    turns = extract_voice_turns(conv)
    return {
        "conversation_id": conv.get("conversation_id") or "",
        "title": conv.get("title") or "",
        "voice": conv.get("voice") or "",
        "turn_count": len(turns),
        "parent_message_id": find_current_node_parent(conv),
        "preview": format_resume_snip(turns, max_chars=240),
    }
