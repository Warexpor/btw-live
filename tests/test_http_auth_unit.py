"""Unit tests that do not need live network (structure only)."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from btw.http_client import ChatGPTClient  # noqa: E402
from btw.session_json import build_voice_session_payload  # noqa: E402
from btw.profiles import load_profile  # noqa: E402


def test_client_builds_headers_shape():
    # won't call network
    c = ChatGPTClient.__new__(ChatGPTClient)
    c.cookie_header = "oai-did=abc; __Secure-next-auth.session-token.0=x"
    c.device_id = "abc"
    c.session_id = "sid"
    c.access_token = "tok"
    c.backend = "test"
    h = ChatGPTClient._headers(c, bearer=True)
    assert h["Authorization"] == "Bearer tok"
    assert h["oai-device-id"] == "abc"
    assert "Cookie" in h


def test_session_payload_has_no_instructions():
    p = load_profile("default")
    s = build_voice_session_payload(p)
    assert "instructions" not in s
    assert s["voice_mode"] == "wingman"
