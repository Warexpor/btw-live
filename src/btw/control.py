"""File IPC so MCP can mute/stop/reinject a running Live process."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .paths import data_dir


def control_path() -> Path:
    return data_dir() / "control.jsonl"


def status_live_path() -> Path:
    return data_dir() / "live_status.json"


def write_live_status(payload: dict[str, Any]) -> None:
    data_dir().mkdir(parents=True, exist_ok=True)
    payload = {**payload, "ts": time.time()}
    status_live_path().write_text(json.dumps(payload, indent=2), encoding="utf-8")


def push_command(cmd: str, **kwargs: Any) -> dict[str, Any]:
    data_dir().mkdir(parents=True, exist_ok=True)
    rec = {"cmd": cmd, "ts": time.time(), **kwargs}
    with control_path().open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")
    return {"ok": True, "queued": rec}


def drain_commands() -> list[dict[str, Any]]:
    p = control_path()
    if not p.is_file():
        return []
    try:
        lines = p.read_text(encoding="utf-8").splitlines()
    except Exception:
        return []
    # clear file
    try:
        p.write_text("", encoding="utf-8")
    except Exception:
        pass
    out = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out
