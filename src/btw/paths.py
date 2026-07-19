from __future__ import annotations

import os
import sys
from pathlib import Path


def plugin_root() -> Path:
    env = os.environ.get("GROK_PLUGIN_ROOT") or os.environ.get("CLAUDE_PLUGIN_ROOT")
    if env:
        return Path(env)
    # src/btw/paths.py -> plugin root
    return Path(__file__).resolve().parents[2]


def python_exe() -> str:
    """Interpreter for MCP + Live spawn. Never fall back to random PATH python.

    Order: BTW_PYTHON → plugin .venv → sys.executable only if it *is* that venv.
    """
    env = (os.environ.get("BTW_PYTHON") or "").strip().strip('"')
    if env and Path(env).is_file():
        return str(Path(env).resolve())

    root = plugin_root()
    for rel in (Path(".venv") / "Scripts" / "python.exe", Path(".venv") / "bin" / "python"):
        cand = root / rel
        if cand.is_file():
            return str(cand.resolve())

    se = Path(sys.executable).resolve()
    try:
        se.relative_to((root / ".venv").resolve())
        return str(se)
    except ValueError:
        pass

    raise RuntimeError(
        f"btw: no plugin .venv python under {root}. "
        "Run install.ps1 (creates .venv). Do not use bare PATH python."
    )


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
