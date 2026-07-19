#!/usr/bin/env python3
import json
import re
from pathlib import Path

CAP = Path(__file__).resolve().parents[1] / "re" / "captures"
raw = (CAP / "realtime_wm_request.txt").read_text(encoding="utf-8")

idx = raw.find('name="session"')
print("session idx", idx)
print("around:", repr(raw[idx : idx + 120]))

# Prefer regex for body after Content-Disposition session
m = re.search(
    r'Content-Disposition:\s*form-data;\s*name="session"\s*\n(?:Content-Type:[^\n]*\n)?\s*\n([\s\S]*?)\n------',
    raw,
)
if not m:
    m = re.search(
        r'name="session"\s*\n\s*\n([\s\S]*?)(?:\n------|\Z)',
        raw,
    )
if not m:
    raise SystemExit("no session body")

body = m.group(1).strip()
# HAR sometimes doubles newlines between every line
if body.count("\n\n") > body.count("\n") * 0.3:
    body = re.sub(r"\n\n+", "\n", body)

# extract JSON object
jm = re.search(r"\{[\s\S]*\}", body)
if not jm:
    raise SystemExit(f"no json in body: {body[:200]!r}")
jtxt = jm.group(0)
try:
    sess = json.loads(jtxt)
except json.JSONDecodeError:
    jtxt = re.sub(r"\n\n+", "\n", jtxt)
    sess = json.loads(jtxt)

(CAP / "realtime_wm_session.json").write_text(json.dumps(sess, indent=2), encoding="utf-8")
print("keys", sorted(sess.keys()))


def red(o):
    if isinstance(o, dict):
        return {k: red(v) for k, v in o.items()}
    if isinstance(o, list):
        return [red(x) for x in o]
    if isinstance(o, str) and len(o) > 50:
        return o[:30] + "…"
    return o


print(json.dumps(red(sess), indent=2))

# sdp field head
sm = re.search(
    r'name="sdp"\s*\n\s*\n([\s\S]*?)(?:\n------|\Z)',
    raw,
)
if sm:
    sdp = sm.group(1).strip()
    sdp = re.sub(r"\n\n+", "\n", sdp)
    (CAP / "realtime_wm_offer.sdp").write_text(sdp, encoding="utf-8")
    print("sdp offer lines", len(sdp.splitlines()), "audio", "m=audio" in sdp, "video", "m=video" in sdp)
