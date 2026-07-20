"""Named /btw-vc sessions: profile + context pack (like Grok /btw context)."""
from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .paths import data_dir
from .profiles import list_profiles, load_profile

_NAME_RE = re.compile(r"^[a-zA-Z0-9 _.-]{1,64}$")


def sessions_path() -> Path:
    return data_dir() / "sessions.json"


@dataclass
class VoiceSession:
    id: str
    name: str
    profile: str = "default"
    context: str = ""
    # Empty string = use profile default voice
    voice: str = ""
    # ChatGPT backend conversation bind (resume / C path)
    conversation_id: str = ""
    last_voice_session_id: str = ""
    parent_message_id: str = ""
    conversation_title: str = ""
    conversation_bound_at: float | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    last_used_at: float | None = None
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> VoiceSession:
        return cls(
            id=str(d["id"]),
            name=str(d["name"]),
            profile=str(d.get("profile") or "default"),
            context=str(d.get("context") or ""),
            voice=str(d.get("voice") or ""),
            conversation_id=str(d.get("conversation_id") or ""),
            last_voice_session_id=str(d.get("last_voice_session_id") or ""),
            parent_message_id=str(d.get("parent_message_id") or ""),
            conversation_title=str(d.get("conversation_title") or ""),
            conversation_bound_at=d.get("conversation_bound_at"),
            created_at=float(d.get("created_at") or time.time()),
            updated_at=float(d.get("updated_at") or time.time()),
            last_used_at=d.get("last_used_at"),
            notes=str(d.get("notes") or ""),
        )


@dataclass
class Store:
    active_id: str | None = None
    sessions: list[VoiceSession] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "active_id": self.active_id,
            "sessions": [s.to_dict() for s in self.sessions],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Store:
        sess = [VoiceSession.from_dict(x) for x in (d.get("sessions") or [])]
        return cls(active_id=d.get("active_id"), sessions=sess)


def load_store() -> Store:
    p = sessions_path()
    if not p.is_file():
        st = Store()
        # default session
        s = VoiceSession(id=str(uuid.uuid4()), name="default", profile="default")
        st.sessions = [s]
        st.active_id = s.id
        save_store(st)
        return st
    try:
        return Store.from_dict(json.loads(p.read_text(encoding="utf-8")))
    except Exception:
        return Store()


def save_store(st: Store) -> None:
    data_dir().mkdir(parents=True, exist_ok=True)
    sessions_path().write_text(json.dumps(st.to_dict(), indent=2), encoding="utf-8")


def _session_public(s: VoiceSession, *, active_id: str | None) -> dict[str, Any]:
    d = s.to_dict()
    d["active"] = s.id == active_id
    d["context_chars"] = len(s.context or "")
    d["context_preview"] = (s.context or "")[:120].replace("\n", " ")
    cid = (s.conversation_id or "").strip()
    d["resume"] = bool(cid)
    d["conversation_short"] = (cid[:8] + "…") if len(cid) > 10 else (cid or None)
    try:
        d["voice_effective"] = effective_voice(s)
    except Exception:
        d["voice_effective"] = s.voice or None
    return d


def list_sessions() -> list[dict[str, Any]]:
    st = load_store()
    return [_session_public(s, active_id=st.active_id) for s in st.sessions]


def get_active() -> VoiceSession:
    st = load_store()
    if not st.sessions:
        s = VoiceSession(id=str(uuid.uuid4()), name="default", profile="default")
        st.sessions = [s]
        st.active_id = s.id
        save_store(st)
        return s
    for s in st.sessions:
        if s.id == st.active_id:
            return s
    st.active_id = st.sessions[0].id
    save_store(st)
    return st.sessions[0]


def create_session(
    name: str,
    profile: str = "default",
    context: str = "",
    voice: str = "",
) -> dict[str, Any]:
    from .voices import normalize_voice

    name = (name or "").strip() or "session"
    if not _NAME_RE.match(name):
        raise ValueError("invalid session name")
    load_profile(profile)  # validate
    voice_s = ""
    if voice:
        voice_s = normalize_voice(voice)
    st = load_store()
    if any(s.name.lower() == name.lower() for s in st.sessions):
        raise ValueError(f"session name already exists: {name}")
    s = VoiceSession(
        id=str(uuid.uuid4()),
        name=name,
        profile=profile,
        context=context or "",
        voice=voice_s,
    )
    st.sessions.append(s)
    st.active_id = s.id
    save_store(st)
    _sync_active_files(s)
    return s.to_dict()


def use_session(id_or_name: str) -> dict[str, Any]:
    st = load_store()
    key = (id_or_name or "").strip()
    for s in st.sessions:
        if s.id == key or s.name.lower() == key.lower():
            st.active_id = s.id
            s.last_used_at = time.time()
            save_store(st)
            _sync_active_files(s)
            return s.to_dict()
    raise FileNotFoundError(f"session not found: {id_or_name}")


def delete_session(id_or_name: str) -> dict[str, Any]:
    st = load_store()
    key = (id_or_name or "").strip()
    keep = []
    deleted = None
    for s in st.sessions:
        if s.id == key or s.name.lower() == key.lower():
            deleted = s
        else:
            keep.append(s)
    if not deleted:
        raise FileNotFoundError(f"session not found: {id_or_name}")
    if not keep:
        keep = [VoiceSession(id=str(uuid.uuid4()), name="default", profile="default")]
    st.sessions = keep
    if st.active_id == deleted.id:
        st.active_id = keep[0].id
    save_store(st)
    active = get_active()
    _sync_active_files(active)
    return {"ok": True, "deleted": deleted.name, "active": active.name}


def update_active(
    *,
    profile: str | None = None,
    context: str | None = None,
    notes: str | None = None,
    name: str | None = None,
    voice: str | None = None,
    conversation_id: str | None = None,
    last_voice_session_id: str | None = None,
    parent_message_id: str | None = None,
    conversation_title: str | None = None,
    conversation_bound_at: float | None = ...,  # type: ignore[assignment]
) -> dict[str, Any]:
    from .voices import normalize_voice

    st = load_store()
    s = get_active()
    for i, x in enumerate(st.sessions):
        if x.id != s.id:
            continue
        if profile is not None:
            load_profile(profile)
            x.profile = profile
        if context is not None:
            x.context = context
        if notes is not None:
            x.notes = notes
        if name is not None:
            name = name.strip()
            if not _NAME_RE.match(name):
                raise ValueError("invalid session name")
            x.name = name
        if voice is not None:
            # empty string clears override → profile default
            x.voice = "" if not str(voice).strip() else normalize_voice(voice)
        if conversation_id is not None:
            x.conversation_id = (conversation_id or "").strip()
        if last_voice_session_id is not None:
            x.last_voice_session_id = (last_voice_session_id or "").strip()
        if parent_message_id is not None:
            x.parent_message_id = (parent_message_id or "").strip()
        if conversation_title is not None:
            x.conversation_title = (conversation_title or "").strip()
        if conversation_bound_at is not ...:
            x.conversation_bound_at = conversation_bound_at
        x.updated_at = time.time()
        st.sessions[i] = x
        save_store(st)
        _sync_active_files(x)
        return x.to_dict()
    raise RuntimeError("active session missing")


def bind_active_conversation(
    conversation_id: str,
    *,
    title: str = "",
    parent_message_id: str = "",
    last_voice_session_id: str | None = None,
) -> dict[str, Any]:
    from .conversation import normalize_conversation_id

    cid = normalize_conversation_id(conversation_id)
    kwargs: dict[str, Any] = {
        "conversation_id": cid,
        "conversation_title": title or "",
        "parent_message_id": parent_message_id or "",
        "conversation_bound_at": time.time(),
    }
    if last_voice_session_id is not None:
        kwargs["last_voice_session_id"] = last_voice_session_id
    return update_active(**kwargs)


def clear_active_conversation() -> dict[str, Any]:
    """Drop ChatGPT bind; keep local pack/profile/voice."""
    return update_active(
        conversation_id="",
        parent_message_id="",
        conversation_title="",
        last_voice_session_id="",
        conversation_bound_at=None,
    )


def set_last_voice_session(voice_session_id: str) -> dict[str, Any]:
    return update_active(last_voice_session_id=(voice_session_id or "").strip())


def effective_voice(session: VoiceSession | None = None) -> str:
    """Session override, else profile default."""
    from .voices import DEFAULT_VOICE, normalize_voice

    s = session or get_active()
    if (s.voice or "").strip():
        return normalize_voice(s.voice)
    try:
        return normalize_voice(load_profile(s.profile).voice)
    except Exception:
        return DEFAULT_VOICE


def touch_active_used() -> None:
    st = load_store()
    for s in st.sessions:
        if s.id == st.active_id:
            s.last_used_at = time.time()
            save_store(st)
            return


def _sync_active_files(s: VoiceSession) -> None:
    """Mirror active session into context.txt / instructions.txt for runtime."""
    data_dir().mkdir(parents=True, exist_ok=True)
    (data_dir() / "context.txt").write_text(s.context or "", encoding="utf-8")
    prof = load_profile(s.profile)
    instructions = prof.assemble_instructions(s.context or "")
    (data_dir() / "instructions.txt").write_text(instructions, encoding="utf-8")
    cid = (s.conversation_id or "").strip()
    (data_dir() / "active_session.json").write_text(
        json.dumps(
            {
                "id": s.id,
                "name": s.name,
                "profile": s.profile,
                "context_chars": len(s.context or ""),
                "profiles_available": list_profiles(),
                "conversation_id": cid or None,
                "resume": bool(cid),
                "conversation_title": s.conversation_title or None,
                "last_voice_session_id": s.last_voice_session_id or None,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
