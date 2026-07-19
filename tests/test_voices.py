from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pytest  # noqa: E402

from btw.voices import list_voices, normalize_voice, DEFAULT_VOICE  # noqa: E402
from btw.session_json import build_voice_session_payload  # noqa: E402
from btw.profiles import load_profile  # noqa: E402


def test_normalize_and_list():
    assert "maple" in list_voices()
    assert normalize_voice("Maple") == "maple"
    assert normalize_voice(None) == DEFAULT_VOICE
    with pytest.raises(ValueError):
        normalize_voice("not-a-real-voice-xyz")


def test_payload_uses_voice_override():
    p = load_profile("default")
    sess = build_voice_session_payload(p, voice="sage")
    assert sess["voice"] == "sage"
