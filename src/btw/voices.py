"""Known ChatGPT Live / web voice IDs (mint `session.voice`)."""
from __future__ import annotations

# Observed in HAR + common ChatGPT voice mode names.
# Server may reject unknown; we validate against this allowlist.
KNOWN_VOICES: tuple[str, ...] = (
    "maple",
    "sol",
    "spruce",
    "vale",
    "breeze",
    "ember",
    "juniper",
    "orbit",
    # legacy / realtime-adjacent names (accepted on some accounts)
    "alloy",
    "ash",
    "ballad",
    "coral",
    "echo",
    "fable",
    "onyx",
    "nova",
    "sage",
    "shimmer",
    "verse",
)

DEFAULT_VOICE = "maple"


def list_voices() -> list[str]:
    return list(KNOWN_VOICES)


def normalize_voice(name: str | None) -> str:
    v = (name or DEFAULT_VOICE).strip().lower()
    if not v:
        return DEFAULT_VOICE
    if v not in KNOWN_VOICES:
        raise ValueError(
            f"unknown voice {name!r}; known: {', '.join(KNOWN_VOICES)}"
        )
    return v
