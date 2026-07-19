from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .paths import sessions_dir

try:
    import tomllib
except ModuleNotFoundError:  # py<3.11
    import tomli as tomllib  # type: ignore


@dataclass(frozen=True)
class SessionProfile:
    name: str
    voice: str
    voice_mode: str
    description: str
    system: str
    context_max_chars: int

    def assemble_instructions(self, context: str | None = None) -> str:
        """Full system prompt sent into the Live session."""
        parts = [
            self.system.strip(),
            "",
            "## Channel contract",
            "This is a Grok Build /btw Live voice side session.",
            "Main coding agent = Grok Build. You = voice advisor only.",
        ]
        ctx = (context or "").strip()
        if ctx:
            if len(ctx) > self.context_max_chars:
                ctx = ctx[: self.context_max_chars] + "\n…[truncated]"
            parts.extend(
                [
                    "",
                    "## Current Grok session context",
                    "(User- or harness-provided snip. Prefer this over guessing.)",
                    ctx,
                ]
            )
        else:
            parts.extend(
                [
                    "",
                    "## Current Grok session context",
                    "(none yet — ask the user to /btw push context if you need it)",
                ]
            )
        return "\n".join(parts).strip() + "\n"


_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


def list_profiles() -> list[str]:
    d = sessions_dir()
    if not d.is_dir():
        return []
    return sorted(p.stem for p in d.glob("*.toml") if _NAME_RE.match(p.stem))


def load_profile(name: str = "default") -> SessionProfile:
    if not _NAME_RE.match(name):
        raise ValueError(f"invalid profile name: {name!r}")
    path = sessions_dir() / f"{name}.toml"
    if not path.is_file():
        available = ", ".join(list_profiles()) or "(none)"
        raise FileNotFoundError(f"profile {name!r} not found; available: {available}")
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    system = (raw.get("system") or "").strip()
    if not system:
        raise ValueError(f"profile {name!r} has empty system prompt")
    return SessionProfile(
        name=str(raw.get("name") or name),
        voice=str(raw.get("voice") or "maple"),
        voice_mode=str(raw.get("voice_mode") or "wingman"),
        description=str(raw.get("description") or ""),
        system=system,
        context_max_chars=int(raw.get("context_max_chars") or 6000),
    )


def profile_path(name: str) -> Path:
    return sessions_dir() / f"{name}.toml"
