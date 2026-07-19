from __future__ import annotations

import os
from pathlib import Path


def plugin_root() -> Path:
    env = os.environ.get("GROK_PLUGIN_ROOT") or os.environ.get("CLAUDE_PLUGIN_ROOT")
    if env:
        return Path(env)
    # src/btw/paths.py -> plugin root
    return Path(__file__).resolve().parents[2]


def data_dir() -> Path:
    env = os.environ.get("GROK_PLUGIN_DATA") or os.environ.get("CLAUDE_PLUGIN_DATA")
    if env:
        p = Path(env)
    else:
        p = Path.home() / ".grok" / "btw"
    p.mkdir(parents=True, exist_ok=True)
    return p


def sessions_dir() -> Path:
    return plugin_root() / "sessions"


def captures_dir() -> Path:
    return plugin_root() / "re" / "captures"


def state_path() -> Path:
    return data_dir() / "state.json"


def cookies_path() -> Path:
    """Prefer plugin data cookies; fall back to RE captures."""
    for p in (data_dir() / "cookies.netscape", captures_dir() / "cookies.netscape"):
        if p.exists():
            return p
    header = captures_dir() / "cookie_header.txt"
    if header.exists():
        return header
    return data_dir() / "cookies.netscape"
