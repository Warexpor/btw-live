#!/usr/bin/env python3
"""Import Cookie header string into netscape + json for probe_session."""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CAP = ROOT / "re" / "captures"


def parse_header(raw: str) -> list[dict]:
    pairs = re.findall(r"(?:^|;\s*)([^=;\s]+)=((?:\"[^\"]*\"|[^;])*)", raw.strip())
    rows = []
    for name, value in pairs:
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] == '"':
            value = value[1:-1]
        if name.startswith("__Host-"):
            domain = "chatgpt.com"
        else:
            domain = ".chatgpt.com"
        rows.append(
            {
                "domain": domain,
                "name": name,
                "value": value,
                "path": "/",
                "secure": True,
                "expires": 0,
                "interesting": (
                    name.startswith("__Secure-next-auth")
                    or name.startswith("oai-")
                    or name.startswith("__Secure-oai")
                    or "session" in name.lower()
                ),
            }
        )
    by_name = {r["name"]: r for r in rows}
    return list(by_name.values())


def main() -> int:
    CAP.mkdir(parents=True, exist_ok=True)
    if len(sys.argv) > 1:
        raw = Path(sys.argv[1]).read_text(encoding="utf-8")
    else:
        raw = (CAP / "cookie_header.txt").read_text(encoding="utf-8")

    rows = parse_header(raw)
    if not rows:
        print("no cookies parsed", file=sys.stderr)
        return 2

    meta = {
        "source": "user_header",
        "extracted_at": datetime.now(timezone.utc).isoformat(),
        "count": len(rows),
    }
    (CAP / "cookies.full.json").write_text(
        json.dumps({"meta": meta, "cookies": rows}, indent=2), encoding="utf-8"
    )

    lines = ["# Netscape HTTP Cookie File", "# from cookie header"]
    for r in rows:
        d = r["domain"]
        sub = "TRUE" if d.startswith(".") else "FALSE"
        lines.append(
            f"{d}\t{sub}\t{r['path']}\tTRUE\t0\t{r['name']}\t{r['value']}"
        )
    (CAP / "cookies.netscape").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"parsed {len(rows)} cookies")
    for r in sorted(rows, key=lambda x: x["name"]):
        print(f"  {r['name']}: len={len(r['value'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
