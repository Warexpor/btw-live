from __future__ import annotations

import re
from typing import Any


def cookie_header_to_playwright(cookie_header: str) -> list[dict[str, Any]]:
    """Convert Cookie header string to Playwright add_cookies() entries."""
    pairs = re.findall(
        r"(?:^|;\s*)([^=;\s]+)=((?:\"[^\"]*\"|[^;])*)",
        cookie_header.strip(),
    )
    out: list[dict[str, Any]] = []
    for name, value in pairs:
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] == '"':
            value = value[1:-1]
        if name.startswith("__Host-"):
            domain = "chatgpt.com"
        else:
            domain = ".chatgpt.com"
        out.append(
            {
                "name": name,
                "value": value,
                "domain": domain,
                "path": "/",
                "secure": True,
                "httpOnly": name.startswith("__Secure-")
                or name.startswith("__Host-")
                or "session" in name.lower(),
                "sameSite": "Lax",
            }
        )
    return out
