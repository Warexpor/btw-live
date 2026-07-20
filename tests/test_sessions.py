from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from btw.session_json import (  # noqa: E402
    instruction_events,
    context_push_events,
    plain_boot_entries,
    plain_topup_entry,
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


def test_plain_boot_entries_are_single_compact():
    entries = plain_boot_entries(
        "You are a debugger.\n\n## Current Grok session context\nFixed spawn.",
        "Fixed spawn.\n\nMic OK.",
    )
    assert len(entries) == 1
    assert isinstance(entries[0], str)
    assert "SESSION BRIEF" in entries[0]
    assert "debugger" in entries[0]
    top = plain_topup_entry("new fact")
    assert top.startswith("[BTW-VC CONTEXT UPDATE")
    assert "new fact" in top


def test_instruction_events_legacy_realtime():
    ev = instruction_events("You are a debugger.\n\nContext: boom")
    types = [e.get("type") for e in ev]
    assert "session.update" in types
    assert "conversation.item.create" in types
    assert "response.create" in types
    assert context_push_events("more")[0]["type"] == "conversation.item.create"
