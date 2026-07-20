from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from btw.session_json import (  # noqa: E402
    instruction_events,
    context_push_events,
    plain_boot_entries,
    plain_boot_message,
    plain_topup_entry,
    plain_topup_message,
    PLAIN_BOOT_MAX,
    PLAIN_TOPUP_MAX,
)


def test_session_crud(tmp_path, monkeypatch):
    monkeypatch.setenv("GROK_PLUGIN_DATA", str(tmp_path))
    # re-import paths? sessions_store uses data_dir which reads env
    from importlib import reload
    import btw.paths as paths
    import btw.sessions_store as store

    reload(paths)
    reload(store)

    s = store.create_session("alpha", profile="debugger", context="fix login")
    assert s["name"] == "alpha"
    assert store.get_active().name == "alpha"
    store.create_session("beta", profile="default")
    store.use_session("alpha")
    assert store.get_active().name == "alpha"
    store.update_active(context="new ctx")
    assert "new ctx" in store.get_active().context
    store.delete_session("beta")
    names = [x["name"] for x in store.list_sessions()]
    assert "beta" not in names


def test_plain_boot_is_single_structured_message():
    msg = plain_boot_message(
        "You are a debugger.\n\n## Current Grok session context\nFixed spawn.",
        "Fixed spawn.\n\nMic OK.",
    )
    assert isinstance(msg, str)
    assert msg.count("[BTW-VC SESSION BRIEF") == 1
    assert "Fixed spawn" in msg
    assert len(msg) <= PLAIN_BOOT_MAX + 20  # clip marker margin
    entries = plain_boot_entries(
        "You are a debugger.\n\n## Current Grok session context\nFixed spawn.",
        "Fixed spawn.\n\nMic OK.",
    )
    assert len(entries) == 1
    assert entries[0] == msg


def test_plain_topup_is_single_whats_new():
    top = plain_topup_message("Meters fixed; testing negotiated DC inject.")
    assert top.count("[BTW-VC WHAT'S NEW]") == 1
    assert "Meters fixed" in top
    assert "Merge into prior" in top
    assert len(top) <= PLAIN_TOPUP_MAX + 20
    # compat alias
    assert plain_topup_entry("x") == plain_topup_message("x")
    assert plain_topup_message("   ") == ""


def test_plain_topup_clips_long_delta():
    huge = "fact line " * 200
    top = plain_topup_message(huge)
    assert len(top) <= PLAIN_TOPUP_MAX + 20
    assert top.startswith("[BTW-VC WHAT'S NEW]")


def test_instruction_events_legacy_realtime():
    ev = instruction_events("You are a debugger.\n\nContext: boom")
    types = [e.get("type") for e in ev]
    assert "session.update" in types
    assert "conversation.item.create" in types
    assert "response.create" in types
    assert context_push_events("more")[0]["type"] == "conversation.item.create"
