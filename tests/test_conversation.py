from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from btw.conversation import (  # noqa: E402
    decode_conversation_payload,
    extract_voice_turns,
    format_resume_snip,
    normalize_conversation_id,
    conversation_summary,
    find_current_node_parent,
)
from btw.session_json import build_voice_session_payload  # noqa: E402
from btw.profiles import load_profile  # noqa: E402
from btw.live_session import spoken_bootstrap  # noqa: E402


FIXTURE = ROOT / "tests" / "fixtures" / "conversation_voice_snip.json"


def test_normalize_conversation_id_uuid_and_url():
    cid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    assert normalize_conversation_id(cid) == cid
    assert (
        normalize_conversation_id(f"https://chatgpt.com/c/{cid}") == cid
    )
    try:
        normalize_conversation_id("not-an-id")
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_extract_voice_turns_from_fixture():
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    turns = extract_voice_turns(raw)
    assert len(turns) == 3
    assert turns[0]["role"] == "you"
    assert "Hello" in turns[0]["text"]
    assert turns[1]["role"] == "ai"
    assert "BANANA" in turns[2]["text"]
    assert turns[0]["voice_session_id"] == "VSID-ONE"
    assert turns[2]["voice_session_id"] == "VSID-TWO"


def test_format_resume_snip_and_summary():
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    turns = extract_voice_turns(raw)
    snip = format_resume_snip(turns, max_chars=500)
    assert "you:" in snip
    assert "ai:" in snip
    assert "BANANA" in snip
    summary = conversation_summary(raw)
    assert summary["turn_count"] == 3
    assert summary["title"] == "Test voice thread"
    assert find_current_node_parent(raw) == "n2"


def test_format_resume_snip_clips():
    turns = [
        {"role": "you", "text": ("word " * 40).strip(), "message_id": str(i), "t": float(i)}
        for i in range(30)
    ]
    snip = format_resume_snip(turns, max_chars=400)
    assert len(snip) <= 450
    assert snip  # non-empty


def test_decode_json_and_empty_mapping():
    d = decode_conversation_payload('{"conversation_id":"x","mapping":{}}')
    assert d["conversation_id"] == "x"
    assert extract_voice_turns(d) == []


def test_payload_includes_conversation_id():
    prof = load_profile("default")
    p = build_voice_session_payload(
        prof, voice_session_id="AAA", conversation_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    )
    assert p["conversation_id"] == "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    assert p["conversation_mode"]["conversation_id"] == p["conversation_id"]
    p2 = build_voice_session_payload(prof, voice_session_id="BBB")
    assert "conversation_id" not in p2


def test_spoken_bootstrap_includes_resume():
    text = spoken_bootstrap(
        "sys",
        "pack fact ALPHA",
        resume_snip="you: hi\nai: hello BANANA",
    )
    assert "BANANA" in text
    assert "ALPHA" in text or "pack" in text.lower() or "fact" in text.lower()
    assert "Prior voice" in text or "prior" in text.lower()


def test_session_bind_fresh(tmp_path, monkeypatch):
    monkeypatch.setenv("GROK_PLUGIN_DATA", str(tmp_path))
    from importlib import reload
    import btw.paths as paths
    import btw.sessions_store as store

    reload(paths)
    reload(store)

    store.create_session("work", profile="default", context="ctx")
    cid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    s = store.bind_active_conversation(cid, title="T")
    assert s["conversation_id"] == cid
    assert s["conversation_title"] == "T"
    listed = store.list_sessions()
    work = next(x for x in listed if x["name"] == "work")
    assert work["resume"] is True
    store.clear_active_conversation()
    assert not store.get_active().conversation_id
