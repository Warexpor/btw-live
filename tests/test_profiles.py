from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from btw.profiles import list_profiles, load_profile  # noqa: E402
from btw.session_json import build_voice_session_payload, instruction_events  # noqa: E402


def test_list_and_load_default():
    names = list_profiles()
    assert "default" in names
    assert "debugger" in names
    p = load_profile("default")
    assert "Grok Build" in p.system or "btw" in p.system.lower()
    assert p.voice == "maple"
    assert p.context_max_chars > 0


def test_assemble_with_context_truncation():
    p = load_profile("default")
    big = "x" * (p.context_max_chars + 500)
    text = p.assemble_instructions(big)
    assert "truncated" in text
    assert "Current Grok session context" in text
    assert "Channel contract" in text


def test_session_payload_and_events():
    p = load_profile("architect")
    sess = build_voice_session_payload(p, voice_session_id="ABC")
    assert sess["voice_mode"] == "wingman"
    assert sess["voice"] == "maple"
    assert sess["voice_session_id"] == "ABC"
    # instructions NOT in mint session object
    assert "instructions" not in sess
    assert "system" not in sess
    ev = instruction_events("hello system")
    assert any(e.get("type") == "session.update" for e in ev)
