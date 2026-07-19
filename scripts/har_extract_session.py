#!/usr/bin/env python3
"""Extract session form JSON + prepare bodies from HAR artifacts."""
from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
CAP = ROOT / "re" / "captures"
HAR = CAP / "chatgpt.com.har"
if not HAR.exists():
    HAR = Path(r"C:\Users\amicu\Desktop\chatgpt.com.har")


def red(o):
    if isinstance(o, dict):
        return {k: red(v) for k, v in o.items()}
    if isinstance(o, list):
        return [red(x) for x in o[:30]] + (["…"] if len(o) > 30 else [])
    if isinstance(o, str) and len(o) > 60:
        return o[:24] + "… len=" + str(len(o))
    return o


def main() -> None:
    data = json.loads(HAR.read_text(encoding="utf-8"))
    entries = data["log"]["entries"]

    auth_count = 0
    for e in entries:
        for h in e["request"].get("headers") or []:
            if h["name"].lower() == "authorization":
                auth_count += 1
                v = h["value"]
                print(
                    "AUTH",
                    e["request"]["method"],
                    urlparse(e["request"]["url"]).path,
                    "len",
                    len(v),
                    "prefix",
                    v[:22],
                )
    print("authorization headers total", auth_count)

    raw = (CAP / "realtime_wm_request.txt").read_text(encoding="utf-8")
    m = re.search(r'name="session"\r?\n\r?\n(\{.*?\})\r?\n', raw, re.S)
    if not m:
        m = re.search(r'name="session"\n\n(\{.*?\})\n', raw, re.S)
    if m:
        sess = json.loads(m.group(1))
        (CAP / "realtime_wm_session.json").write_text(
            json.dumps(sess, indent=2), encoding="utf-8"
        )
        print("session keys", sorted(sess.keys()))
        print(json.dumps(red(sess), indent=2))
    else:
        print("session field not found")
        print(repr(raw[:300]))

    print("\n=== prepare ===")
    for e in entries:
        if "conversation/prepare" not in e["request"]["url"]:
            continue
        post = (e["request"].get("postData") or {}).get("text") or ""
        resp = (e["response"].get("content") or {}).get("text") or ""
        pj = json.loads(post)
        rj = json.loads(resp)
        (CAP / "prepare_req.json").write_text(json.dumps(pj, indent=2), encoding="utf-8")
        (CAP / "prepare_resp.json").write_text(json.dumps(rj, indent=2), encoding="utf-8")
        if rj.get("conduit_token"):
            (CAP / "conduit_token.txt").write_text(rj["conduit_token"], encoding="utf-8")
        print("REQ", json.dumps(red(pj), indent=2))
        print("RESP", json.dumps(red(rj), indent=2))
        print("---")

    resp = (CAP / "realtime_wm_response.txt").read_text(encoding="utf-8")
    print("\n=== SDP answer lines ===")
    print("len", len(resp))
    for line in resp.splitlines():
        if not line:
            continue
        if line.startswith(("v=", "o=", "s=", "t=", "c=", "b=", "m=", "a=")):
            if "ice-pwd" in line or "fingerprint" in line:
                print(line[:40] + "…")
            else:
                print(line[:140])

    # voice_mode events from ces
    print("\n=== voice_mode / model telemetry samples ===")
    seen = set()
    for e in entries:
        post = (e["request"].get("postData") or {}).get("text") or ""
        if "voice_mode" not in post and "wingman" not in post:
            continue
        for pat in (
            r'"voice_mode"\s*:\s*"([^"]+)"',
            r'"model"\s*:\s*"([^"]+)"',
            r'"plan_type"\s*:\s*"([^"]+)"',
            r'"surface"\s*:\s*"([^"]+)"',
            r'"event"\s*:\s*"([^"]+)"',
        ):
            for mm in re.finditer(pat, post):
                key = (pat, mm.group(1))
                if key not in seen:
                    seen.add(key)
                    print(f"  {mm.group(1)}")


if __name__ == "__main__":
    main()
