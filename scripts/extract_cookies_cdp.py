#!/usr/bin/env python3
"""Extract cookies via Chrome DevTools Protocol (bypasses DPAPI/ABE).

Chrome must expose remote debugging, e.g.:

  # Fully quit Chrome first, then:
  & "$env:ProgramFiles\Google\Chrome\Application\chrome.exe" `
    --remote-debugging-port=9222 `
    --user-data-dir="$env:LOCALAPPDATA\Google\Chrome\User Data"

Or use a copy profile if the main profile is locked:

  chrome.exe --remote-debugging-port=9222 --user-data-dir=C:\temp\chrome-cdp-profile
  # then log into chatgpt.com once in that window

Usage:
  python scripts/extract_cookies_cdp.py
  python scripts/extract_cookies_cdp.py --port 9222
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen

try:
    import websocket
except ImportError:
    print("pip install websocket-client", file=sys.stderr)
    sys.exit(1)

ROOT = Path(__file__).resolve().parents[1]
CAP = ROOT / "re" / "captures"
DOMAINS = ("chatgpt.com", "openai.com", "chat.openai.com")
INTERESTING_PREFIX = ("__Secure-next-auth", "oai-", "_account", "cf_", "__cf")


def cdp_http(port: int, path: str):
    with urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as r:
        return json.loads(r.read().decode())


def get_ws_url(port: int) -> str:
    # Prefer an existing chatgpt tab; else any page; else browser target
    try:
        tabs = cdp_http(port, "/json/list")
    except Exception as e:
        raise SystemExit(
            f"Cannot reach Chrome CDP on port {port}: {e}\n"
            "Start Chrome with --remote-debugging-port=9222 (see script docstring)."
        ) from e

    for t in tabs:
        url = t.get("url") or ""
        if "chatgpt.com" in url and t.get("webSocketDebuggerUrl"):
            return t["webSocketDebuggerUrl"]
    for t in tabs:
        if t.get("type") == "page" and t.get("webSocketDebuggerUrl"):
            return t["webSocketDebuggerUrl"]
    ver = cdp_http(port, "/json/version")
    if ver.get("webSocketDebuggerUrl"):
        return ver["webSocketDebuggerUrl"]
    raise SystemExit("No CDP websocket target found")


def cdp_call(ws, method: str, params: dict | None = None, msg_id: int = 1):
    payload = {"id": msg_id, "method": method}
    if params:
        payload["params"] = params
    ws.send(json.dumps(payload))
    while True:
        raw = ws.recv()
        data = json.loads(raw)
        if data.get("id") == msg_id:
            if "error" in data:
                raise RuntimeError(data["error"])
            return data.get("result") or {}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=9222)
    args = ap.parse_args()

    CAP.mkdir(parents=True, exist_ok=True)
    ws_url = get_ws_url(args.port)
    ws = websocket.create_connection(ws_url, timeout=10)

    # Network.getAllCookies works on page targets
    try:
        result = cdp_call(ws, "Network.getAllCookies")
        cookies = result.get("cookies") or []
    except Exception:
        # Fallback Storage.getCookies if available
        result = cdp_call(ws, "Storage.getCookies")
        cookies = result.get("cookies") or []
    ws.close()

    rows = []
    for c in cookies:
        domain = c.get("domain") or ""
        if not any(d in domain for d in DOMAINS):
            continue
        name = c.get("name") or ""
        interesting = name.startswith(INTERESTING_PREFIX) or "session" in name.lower()
        rows.append(
            {
                "domain": domain,
                "name": name,
                "value": c.get("value") or "",
                "path": c.get("path") or "/",
                "secure": bool(c.get("secure")),
                "expires": c.get("expires"),
                "httpOnly": bool(c.get("httpOnly")),
                "interesting": interesting,
            }
        )
    rows.sort(key=lambda r: (not r["interesting"], r["domain"], r["name"]))

    if not rows:
        print(
            "CDP connected but no chatgpt/openai cookies.\n"
            "Open https://chatgpt.com in the debug Chrome window and log in.",
            file=sys.stderr,
        )
        return 2

    meta = {
        "source": "cdp",
        "port": args.port,
        "extracted_at": datetime.now(timezone.utc).isoformat(),
        "count": len(rows),
        "interesting_count": sum(1 for r in rows if r["interesting"]),
    }

    full_path = CAP / "cookies.full.json"
    redacted_path = CAP / "cookies.json"
    netscape_path = CAP / "cookies.netscape"

    full_path.write_text(
        json.dumps({"meta": meta, "cookies": rows}, indent=2), encoding="utf-8"
    )
    redacted = []
    for r in rows:
        rr = {k: v for k, v in r.items() if k != "value"}
        v = r["value"]
        rr["value_len"] = len(v)
        rr["value_preview"] = (v[:6] + "…") if len(v) > 6 else "***"
        redacted.append(rr)
    redacted_path.write_text(
        json.dumps({"meta": meta, "cookies": redacted}, indent=2), encoding="utf-8"
    )

    lines = ["# Netscape HTTP Cookie File", "# CDP extract"]
    for r in rows:
        domain = r["domain"]
        include_sub = "TRUE" if domain.startswith(".") else "FALSE"
        secure = "TRUE" if r["secure"] else "FALSE"
        exp = int(float(r["expires"] or 0))
        lines.append(
            f"{domain}\t{include_sub}\t{r['path']}\t{secure}\t{exp}\t{r['name']}\t{r['value']}"
        )
    netscape_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"cdp cookies={len(rows)} interesting={meta['interesting_count']}")
    print(f"wrote {redacted_path}")
    print(f"wrote {full_path} (SECRETS)")
    print(f"wrote {netscape_path}")
    for r in rows:
        if r["interesting"]:
            print(f"  {r['domain']}\t{r['name']}\tlen={len(r['value'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
