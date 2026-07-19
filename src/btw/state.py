from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from typing import Any

from .paths import state_path


@dataclass
class BtwState:
    profile: str = "default"
    status: str = "idle"  # idle | starting | live | error | stopped
    voice_session_id: str | None = None
    oai_session_id: str | None = None
    session_name: str = "default"
    session_id: str | None = None
    muted: bool = False
    started_at: float | None = None
    last_error: str | None = None
    context_chars: int = 0
    context_preview: str = ""
    instructions_chars: int = 0
    mint_ok: bool | None = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> BtwState:
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in d.items() if k in known})


def load_state() -> BtwState:
    p = state_path()
    if not p.is_file():
        return BtwState()
    try:
        return BtwState.from_dict(json.loads(p.read_text(encoding="utf-8")))
    except Exception:
        return BtwState()


def save_state(st: BtwState) -> None:
    state_path().write_text(json.dumps(st.to_dict(), indent=2), encoding="utf-8")


def set_context(st: BtwState, context: str) -> BtwState:
    st.context_chars = len(context or "")
    st.context_preview = (context or "")[:240].replace("\n", " ")
    save_state(st)
    return st


def mark_starting(st: BtwState, profile: str) -> BtwState:
    st.profile = profile
    st.status = "starting"
    st.started_at = time.time()
    st.last_error = None
    save_state(st)
    return st


def mark_live(st: BtwState, voice_session_id: str, instructions_chars: int) -> BtwState:
    st.status = "live"
    st.voice_session_id = voice_session_id
    st.instructions_chars = instructions_chars
    st.mint_ok = True
    save_state(st)
    return st


def mark_error(st: BtwState, err: str) -> BtwState:
    st.status = "error"
    st.last_error = err
    st.mint_ok = False
    save_state(st)
    return st


def mark_stopped(st: BtwState) -> BtwState:
    st.status = "stopped"
    st.muted = False
    save_state(st)
    return st
