"""File IPC so MCP can mute/stop/reinject a running Live process."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from .paths import data_dir


def control_path() -> Path:
    return data_dir() / "control.jsonl"


def status_live_path() -> Path:
    return data_dir() / "live_status.json"


def meters_path() -> Path:
    """High-rate levels for the voice visualizer (~20 Hz)."""
    return data_dir() / "meters.json"


def viz_pid_path() -> Path:
    return data_dir() / "viz.pid"


def write_live_status(payload: dict[str, Any]) -> None:
    data_dir().mkdir(parents=True, exist_ok=True)
    payload = {**payload, "ts": time.time()}
    status_live_path().write_text(json.dumps(payload, indent=2), encoding="utf-8")


def write_meters(payload: dict[str, Any]) -> None:
    """Atomic-ish write of level meters (no pretty indent — hot path)."""
    data_dir().mkdir(parents=True, exist_ok=True)
    payload = {**payload, "ts": time.time()}
    path = meters_path()
    tmp = path.with_suffix(".json.tmp")
    raw = json.dumps(payload, separators=(",", ":"))
    try:
        tmp.write_text(raw, encoding="utf-8")
        os.replace(tmp, path)
    except Exception:
        try:
            path.write_text(raw, encoding="utf-8")
        except Exception:
            pass


def read_meters() -> dict[str, Any]:
    p = meters_path()
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def mark_live_status_stopped(**extra: Any) -> None:
    """Clear ghost 'live' status after kill/stop (pid gone)."""
    write_live_status({"status": "stopped", **extra})
    write_meters({"status": "stopped", "uplink_peak": 0.0, "downlink_peak": 0.0, **extra})


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
