"""Control.jsonl IPC: clear on demand; drain returns then empties."""
from __future__ import annotations

from btw import control


def test_clear_commands_drops_pending(tmp_path, monkeypatch):
    monkeypatch.setattr(control, "data_dir", lambda: tmp_path)
    control.push_command("stop")
    control.push_command("mute")
    control.push_command("stop")
    assert control.control_path().read_text(encoding="utf-8").count("\n") == 3
    control.clear_commands()
    assert control.control_path().read_text(encoding="utf-8") == ""
    assert control.drain_commands() == []


def test_drain_returns_then_clears(tmp_path, monkeypatch):
    monkeypatch.setattr(control, "data_dir", lambda: tmp_path)
    control.push_command("mute")
    control.push_command("stop")
    batch = control.drain_commands()
    assert [r["cmd"] for r in batch] == ["mute", "stop"]
    assert control.drain_commands() == []
