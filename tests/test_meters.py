"""Meters IPC for the voice visualizer."""
from __future__ import annotations

import json
from pathlib import Path

import btw.control as control


def test_write_read_meters(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(control, "data_dir", lambda: tmp_path)
    control.write_meters(
        {
            "status": "live",
            "uplink_peak": 0.25,
            "downlink_peak": 0.1,
            "muted": False,
            "injecting": True,
            "session_name": "default",
            "voice": "maple",
        }
    )
    p = tmp_path / "meters.json"
    assert p.is_file()
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["status"] == "live"
    assert data["uplink_peak"] == 0.25
    assert data["injecting"] is True
    assert "ts" in data

    got = control.read_meters()
    assert got["voice"] == "maple"
    assert got["downlink_peak"] == 0.1


def test_mark_stopped_clears_meters(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(control, "data_dir", lambda: tmp_path)
    control.write_meters({"status": "live", "uplink_peak": 0.9})
    control.mark_live_status_stopped(session_name="demo")
    m = control.read_meters()
    assert m["status"] == "stopped"
    assert m["uplink_peak"] == 0.0
