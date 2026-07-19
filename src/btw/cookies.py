from __future__ import annotations

import json
import re
from pathlib import Path

from .paths import captures_dir, data_dir


def load_cookie_header(path: Path | None = None) -> str:
    """Return Cookie header string from header file, netscape, or full json."""
    candidates: list[Path] = []
    if path:
        candidates.append(path)
    candidates.extend(
        [
            data_dir() / "cookie_header.txt",
            captures_dir() / "cookie_header.txt",
            data_dir() / "cookies.netscape",
            captures_dir() / "cookies.netscape",
            data_dir() / "cookies.full.json",
            captures_dir() / "cookies.full.json",
        ]
    )
    for p in candidates:
        if not p.is_file():
            continue
        text = p.read_text(encoding="utf-8").strip()
        if not text:
            continue
        if p.suffix == ".json" or text.startswith("{"):
            data = json.loads(text)
            rows = data.get("cookies") if isinstance(data, dict) else data
            return "; ".join(f"{c['name']}={c['value']}" for c in rows)
        if "Netscape" in text.splitlines()[0] or "\t" in text.splitlines()[-1]:
            parts = []
            for line in text.splitlines():
                if not line or line.startswith("#"):
                    continue
                cols = line.split("\t")
                if len(cols) >= 7:
                    parts.append(f"{cols[5]}={cols[6]}")
            if parts:
                return "; ".join(parts)
        # raw Cookie header
        if "=" in text and "\t" not in text.splitlines()[0]:
            return text.replace("\n", "").strip()
    raise FileNotFoundError(
        "No cookies found. Save cookie header to ~/.grok/btw/cookie_header.txt "
        "or re/captures/cookie_header.txt"
    )


def oai_did(cookie_header: str) -> str | None:
    m = re.search(r"(?:^|;\s*)oai-did=([^;]+)", cookie_header)
    return m.group(1).strip() if m else None


def clear_token_cache() -> bool:
    p = data_dir() / "access_token_cache.json"
    if p.is_file():
        p.unlink(missing_ok=True)
        return True
    return False


def clear_cookies() -> dict:
    """Remove stored cookies + token cache (account logout local)."""
    removed = []
    for name in (
        "cookie_header.txt",
        "cookies.netscape",
        "cookies.full.json",
        "access_token_cache.json",
    ):
        p = data_dir() / name
        if p.is_file():
            p.unlink(missing_ok=True)
            removed.append(name)
    return {"ok": True, "removed": removed, "data_dir": str(data_dir())}


def import_cookie_header(raw: str) -> Path:
    """Persist user-pasted Cookie header into plugin data dir."""
    data_dir().mkdir(parents=True, exist_ok=True)
    path = data_dir() / "cookie_header.txt"
    path.write_text(raw.strip() + "\n", encoding="utf-8")
    # also mirror netscape-ish for tools that expect it
    pairs = re.findall(r"(?:^|;\s*)([^=;\s]+)=((?:\"[^\"]*\"|[^;])*)", raw.strip())
    lines = ["# Netscape HTTP Cookie File", "# btw import"]
    for name, value in pairs:
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] == '"':
            value = value[1:-1]
        domain = "chatgpt.com" if name.startswith("__Host-") else ".chatgpt.com"
        sub = "FALSE" if domain == "chatgpt.com" else "TRUE"
        lines.append(f"{domain}\t{sub}\t/\tTRUE\t0\t{name}\t{value}")
    (data_dir() / "cookies.netscape").write_text("\n".join(lines) + "\n", encoding="utf-8")
    clear_token_cache()
    return path
