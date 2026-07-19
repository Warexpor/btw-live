#!/usr/bin/env python3
"""Analyze ChatGPT HAR for Live / realtime / conversation endpoints. No secrets printed."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
CAP = ROOT / "re" / "captures"


def redact(s: str | None, n: int = 12) -> str | None:
    if s is None:
        return None
    s = str(s)
    if len(s) <= n * 2:
        return f"len={len(s)}"
    return f"{s[:n]}…{s[-6:]} len={len(s)}"


def hdrs(hlist) -> dict[str, str]:
    return {h["name"].lower(): h["value"] for h in (hlist or [])}


def shallow_summary(obj):
    if not isinstance(obj, dict):
        return type(obj).__name__
    out = {}
    for k, v in obj.items():
        if isinstance(v, str) and len(v) > 40:
            out[k] = redact(v, 8)
        elif isinstance(v, (int, float, bool)) or v is None:
            out[k] = v
        elif isinstance(v, list):
            out[k] = f"list len={len(v)}"
        elif isinstance(v, dict):
            out[k] = f"dict keys={sorted(v.keys())[:20]}"
        else:
            out[k] = type(v).__name__
    return out


def main() -> int:
    har_path = Path(sys.argv[1]) if len(sys.argv) > 1 else CAP / "chatgpt.com.har"
    if not har_path.exists():
        print("missing har", har_path, file=sys.stderr)
        return 2

    data = json.loads(har_path.read_text(encoding="utf-8", errors="replace"))
    entries = data["log"]["entries"]
    print(f"entries={len(entries)} har={har_path}")

    print("\n=== ALL POST/PUT ===")
    for e in entries:
        m = e["request"]["method"]
        if m in ("POST", "PUT", "PATCH"):
            u = e["request"]["url"]
            st = e["response"]["status"]
            p = urlparse(u)
            print(f"{st} {m} {p.path}?{p.query[:100]}")

    focus = []
    for e in entries:
        path = urlparse(e["request"]["url"]).path
        if any(
            x in path
            for x in (
                "/realtime",
                "conversation",
                "voice",
                "prepare",
                "init",
                "session",
                "/wm",
                "turn",
                "iceserver",
                "ces/",
            )
        ):
            focus.append(e)

    out = []
    for e in focus:
        req = e["request"]
        resp = e["response"]
        url = req["url"]
        rh = hdrs(req.get("headers"))
        keep_h = {}
        for k, v in rh.items():
            if not any(
                x in k
                for x in (
                    "auth",
                    "cookie",
                    "oai",
                    "openai",
                    "content-type",
                    "accept",
                    "referer",
                    "origin",
                    "user-agent",
                    "sec-",
                    "x-",
                    "sentinel",
                )
            ):
                continue
            if k == "cookie":
                names = [c.split("=")[0].strip() for c in v.split(";")]
                keep_h[k] = {"names": names, "count": len(names)}
            elif "auth" in k or "token" in k or k == "authorization":
                keep_h[k] = redact(v, 16)
            elif k.startswith("oai-") or "openai" in k or "sentinel" in k:
                keep_h[k] = redact(v, 20) if len(v) > 40 else v
            else:
                keep_h[k] = v if len(v) < 160 else redact(v, 20)

        post = req.get("postData") or {}
        post_text = post.get("text") or ""
        post_mime = post.get("mimeType")
        resp_text = (resp.get("content") or {}).get("text") or ""
        resp_mime = (resp.get("content") or {}).get("mimeType")

        fields = re.findall(r'name="([^"]+)"', post_text)

        req_keys = resp_keys = None
        req_summary = resp_summary = None
        if post_text.strip().startswith("{"):
            try:
                j = json.loads(post_text)
                req_keys = sorted(j.keys()) if isinstance(j, dict) else type(j).__name__
                req_summary = shallow_summary(j)
            except Exception as ex:
                req_keys = f"err:{ex}"
        if resp_text.strip()[:1] in "{[":
            try:
                j = json.loads(resp_text)
                if isinstance(j, dict):
                    resp_keys = sorted(j.keys())
                    resp_summary = shallow_summary(j)
                elif isinstance(j, list):
                    resp_keys = f"list len={len(j)}"
            except Exception:
                pass

        sdp_meta = {}
        for label, text in (("req", post_text), ("resp", resp_text)):
            if "v=0" in text and ("m=audio" in text or "IN IP4" in text):
                sdp_meta[label] = {
                    "len": len(text),
                    "has_audio": "m=audio" in text,
                    "has_video": "m=video" in text,
                    "ice_ufrag": bool(re.search(r"a=ice-ufrag:", text)),
                    "fingerprint": bool(re.search(r"a=fingerprint:", text)),
                    "setup": re.findall(r"a=setup:(\w+)", text)[:4],
                    "mid": re.findall(r"a=mid:([^\r\n]+)", text)[:6],
                    "candidates": len(re.findall(r"a=candidate:", text)),
                }

        # telemetry: extract non-secret voice fields
        tele = {}
        if "livekit" in post_text.lower() or "voice_mode" in post_text.lower():
            for pat in (
                r'"voice_mode"\s*:\s*"([^"]+)"',
                r'"plan_type"\s*:\s*"([^"]+)"',
                r'"surface"\s*:\s*"([^"]+)"',
                r'"livekit_connect_time"\s*:\s*"([^"]+)"',
                r'"model"\s*:\s*"([^"]+)"',
            ):
                m = re.search(pat, post_text)
                if m:
                    tele[pat] = m.group(1)

        item = {
            "status": resp.get("status"),
            "method": req.get("method"),
            "url": url.split("?")[0],
            "path": urlparse(url).path,
            "query": urlparse(url).query,
            "req_headers": keep_h,
            "post_mime": post_mime,
            "post_len": len(post_text),
            "multipart_fields": fields,
            "req_json_keys": req_keys,
            "req_summary": req_summary,
            "resp_mime": resp_mime,
            "resp_len": len(resp_text),
            "resp_json_keys": resp_keys,
            "resp_summary": resp_summary,
            "sdp_meta": sdp_meta,
            "telemetry_bits": tele,
            "started": e.get("startedDateTime"),
            "time_ms": e.get("time"),
        }
        out.append(item)

    CAP.mkdir(parents=True, exist_ok=True)
    out_path = CAP / "har_focus.json"
    out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"\nwrote {out_path} items={len(out)}")

    # Extract realtime/wm raw SDP exchange structure (no full dump to stdout)
    for e in entries:
        path = urlparse(e["request"]["url"]).path
        if path.endswith("/realtime/wm") or path == "/realtime/wm":
            post = (e["request"].get("postData") or {}).get("text") or ""
            resp = (e["response"].get("content") or {}).get("text") or ""
            # save full for local RE only
            (CAP / "realtime_wm_request.txt").write_text(post, encoding="utf-8")
            (CAP / "realtime_wm_response.txt").write_text(resp, encoding="utf-8")
            print("saved realtime_wm_request/response.txt")

            # list form field names + sizes
            parts = re.split(r"\r?\n--", post)
            print("\n=== /realtime/wm form parts ===")
            for part in parts:
                m = re.search(r'name="([^"]+)"(?:;\s*filename="([^"]+)")?', part)
                if not m:
                    continue
                name, fname = m.group(1), m.group(2)
                # body after blank line
                body = part.split("\r\n\r\n", 1)
                if len(body) < 2:
                    body = part.split("\n\n", 1)
                b = body[1] if len(body) > 1 else ""
                b = b.strip("\r\n-")
                print(f"  field={name!r} filename={fname!r} body_len={len(b)} head={b[:60]!r}")

            # headers for wm
            rh = hdrs(e["request"].get("headers"))
            print("\n=== /realtime/wm headers (redacted) ===")
            for k in sorted(rh):
                if any(
                    x in k
                    for x in (
                        "auth",
                        "oai",
                        "openai",
                        "cookie",
                        "content",
                        "accept",
                        "origin",
                        "referer",
                        "user-agent",
                        "sentinel",
                        "x-",
                    )
                ):
                    v = rh[k]
                    if k == "cookie":
                        print(f"  {k}: names={[c.split('=')[0].strip() for c in v.split(';')]}")
                    elif len(v) > 80:
                        print(f"  {k}: {redact(v, 20)}")
                    else:
                        print(f"  {k}: {v}")

    # Print condensed timeline for key paths
    print("\n=== FOCUS TIMELINE ===")
    for item in out:
        if "ces/" in item["path"] and not item["telemetry_bits"]:
            continue
        print(
            f"{item['status']} {item['method']:6} {item['path']}"
            f" post={item['post_len']} resp={item['resp_len']} sdp={bool(item['sdp_meta'])}"
        )
        if item["multipart_fields"]:
            print(f"    multipart: {item['multipart_fields']}")
        if item["req_summary"]:
            print(f"    req: {json.dumps(item['req_summary'])[:400]}")
        if item["resp_summary"]:
            print(f"    resp: {json.dumps(item['resp_summary'])[:500]}")
        if item["sdp_meta"]:
            print(f"    sdp: {item['sdp_meta']}")
        if item["telemetry_bits"]:
            print(f"    tele: {item['telemetry_bits']}")
        # auth presence
        auth = item["req_headers"].get("authorization")
        if auth:
            print(f"    authorization: {auth}")
        for k, v in item["req_headers"].items():
            if k.startswith("oai") or "sentinel" in k or "openai" in k:
                print(f"    {k}: {v}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
