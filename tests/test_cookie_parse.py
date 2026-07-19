from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from btw.cookie_parse import cookie_header_to_playwright  # noqa: E402


def test_parse_basic():
    h = "oai-did=abc-123; __Secure-next-auth.session-token.0=eyJhello; __Host-next-auth.csrf-token=x%7Cy"
    rows = cookie_header_to_playwright(h)
    by = {r["name"]: r for r in rows}
    assert by["oai-did"]["domain"] == ".chatgpt.com"
    assert by["__Host-next-auth.csrf-token"]["domain"] == "chatgpt.com"
    assert by["__Secure-next-auth.session-token.0"]["secure"] is True
