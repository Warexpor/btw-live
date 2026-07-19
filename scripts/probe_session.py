#!/usr/bin/env python3
"""Use extracted cookies to hit chatgpt.com session/bootstrap endpoints."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
CAP = ROOT / "re" / "captures"
OUT = CAP / "probe_session.json"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36"
)

PROBES = [
    ("GET", "https://chatgpt.com/api/auth/session"),
    ("GET", "https://chatgpt.com/backend-api/me"),
    ("GET", "https://chatgpt.com/backend-api/accounts/check/v4-2023-04-27"),
    ("GET", "https://chatgpt.com/backend-api/settings/user"),
    ("GET", "https://chatgpt.com/backend-api/conversations?offset=0&limit=1"),
]


def load_cookie_header() -> str:
    header_file = CAP / "cookie_header.txt"
    if header_file.exists():
        return header_file.read_text(encoding="utf-8").strip()

    full = CAP / "cookies.full.json"
    if full.exists():
        data = json.loads(full.read_text(encoding="utf-8"))
        parts = [f"{c['name']}={c['value']}" for c in data["cookies"]]
        return "; ".join(parts)

    print("no cookies — import header or extract first", file=sys.stderr)
    sys.exit(2)


def oai_did_from_header(cookie: str) -> str | None:
    for part in cookie.split(";"):
        part = part.strip()
        if part.startswith("oai-did="):
            return part.split("=", 1)[1]
    return None


def main() -> int:
    cookie = load_cookie_header()
    did = oai_did_from_header(cookie) or "c500fa29-a233-43a0-af9b-fc71c1a886b6"

    s = requests.Session()
    s.headers.update(
        {
            "User-Agent": UA,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://chatgpt.com/",
            "Origin": "https://chatgpt.com",
            "Cookie": cookie,
            "oai-language": "en-US",
            "oai-device-id": did,
            "sec-ch-ua": '"Chromium";v="150", "Not A(Brand";v="24", "Google Chrome";v="150"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
        }
    )

    results = []
    access_token = None

    for method, url in PROBES:
        try:
            r = s.request(method, url, timeout=30)
            entry = {
                "method": method,
                "url": url,
                "status": r.status_code,
                "content_type": r.headers.get("content-type"),
                "cf_ray": r.headers.get("cf-ray"),
                "body_len": len(r.content or b""),
                "body_preview": (r.text or "")[:800],
            }
            try:
                data = r.json()
                if isinstance(data, dict):
                    entry["json_keys"] = sorted(data.keys())
                    user = data.get("user")
                    if isinstance(user, dict):
                        entry["user_email"] = user.get("email")
                    token = data.get("accessToken") or data.get("access_token")
                    if token:
                        access_token = token
                        entry["has_accessToken"] = True
            except Exception:
                pass
            results.append(entry)
            print(f"{r.status_code} {method} {url} keys={entry.get('json_keys')}")
        except Exception as e:
            results.append({"method": method, "url": url, "error": str(e)})
            print(f"ERR {method} {url}: {e}")

    # If we got access token, re-probe backend with Bearer
    if access_token:
        (CAP / "access_token.txt").write_text(access_token, encoding="utf-8")
        print("access token saved (SECRETS)")
        s.headers["Authorization"] = f"Bearer {access_token}"
        for method, url in PROBES[1:3]:
            r = s.request(method, url, timeout=30)
            print(f"AUTH {r.status_code} {url}")
            results.append(
                {
                    "method": method,
                    "url": url + "#bearer",
                    "status": r.status_code,
                    "body_preview": (r.text or "")[:400],
                }
            )

    OUT.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
