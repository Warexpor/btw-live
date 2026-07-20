"""ChatGPT HTTP client (no Live browser tab). Cookies + token + mint."""
from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

from . import cookies as cookie_mod
from .paths import data_dir

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36"
)

DEFAULT_OAI_CLIENT_VERSION = os.environ.get(
    "BTW_OAI_CLIENT_VERSION",
    "prod-fb4a8a2a751dfec391053cfd7b01c52699ccf78c",
)
DEFAULT_OAI_BUILD = os.environ.get("BTW_OAI_CLIENT_BUILD", "8370486")

IMPERSONATE_CANDIDATES = [
    os.environ.get("BTW_IMPERSONATE", ""),
    "chrome136",
    "chrome131",
    "chrome124",
    "chrome120",
    "chrome",
    "edge101",
]


def _token_cache_path() -> Path:
    return data_dir() / "access_token_cache.json"


def _load_token_cache() -> str | None:
    p = _token_cache_path()
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        exp = float(data.get("expires_at") or 0)
        if exp and time.time() > exp - 60:
            return None
        tok = data.get("accessToken")
        return tok if tok else None
    except Exception:
        return None


def _save_token_cache(token: str, expires_at: float | None = None) -> None:
    data_dir().mkdir(parents=True, exist_ok=True)
    # default 25 min if unknown
    exp = expires_at or (time.time() + 25 * 60)
    _token_cache_path().write_text(
        json.dumps({"accessToken": token, "expires_at": exp, "saved_at": time.time()}),
        encoding="utf-8",
    )


def _cffi_get(url: str, headers: dict, impersonate: str):
    from curl_cffi import requests as crequests

    return crequests.get(url, headers=headers, timeout=45, impersonate=impersonate)


def _cffi_post(url: str, headers: dict, files: dict, impersonate: str):
    from curl_cffi import requests as crequests

    return crequests.post(
        url, headers=headers, files=files, timeout=60, impersonate=impersonate
    )


def _playwright_access_token(cookie_header: str) -> str:
    """Last-resort: headless Chromium only to read /api/auth/session (not Live)."""
    from playwright.sync_api import sync_playwright

    from .cookie_parse import cookie_header_to_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(user_agent=UA)
        ctx.add_cookies(cookie_header_to_playwright(cookie_header))
        page = ctx.new_page()
        page.goto("https://chatgpt.com/", wait_until="domcontentloaded", timeout=120_000)
        page.wait_for_timeout(2000)
        for _ in range(12):
            probe = page.evaluate(
                """async () => {
                  const r = await fetch('/api/auth/session', {credentials:'include'});
                  const t = await r.text();
                  let token=null, exp=null;
                  try {
                    const j = JSON.parse(t);
                    token = j.accessToken || null;
                    exp = j.expires || null;
                  } catch(e) {}
                  return {status:r.status, token, exp, head:t.slice(0,40)};
                }"""
            )
            if probe and probe.get("token"):
                browser.close()
                tok = probe["token"]
                # expires is often ISO string
                exp_at = None
                if probe.get("exp"):
                    try:
                        from datetime import datetime

                        exp_at = datetime.fromisoformat(
                            str(probe["exp"]).replace("Z", "+00:00")
                        ).timestamp()
                    except Exception:
                        exp_at = None
                _save_token_cache(tok, exp_at)
                return tok
            page.wait_for_timeout(1000)
        browser.close()
    raise RuntimeError("playwright token fallback failed (CF or cookies)")


class ChatGPTClient:
    def __init__(self, cookie_header: str | None = None):
        self.cookie_header = cookie_header or cookie_mod.load_cookie_header()
        self.device_id = cookie_mod.oai_did(self.cookie_header) or str(uuid.uuid4())
        self.session_id = str(uuid.uuid4())
        self.access_token: str | None = None
        self.backend = "none"
        self.impersonate: str | None = None

    def _headers(self, *, bearer: bool = False, extra: dict | None = None) -> dict[str, str]:
        h = {
            "User-Agent": UA,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Origin": "https://chatgpt.com",
            "Referer": "https://chatgpt.com/",
            "Cookie": self.cookie_header,
            "oai-device-id": self.device_id,
            "oai-session-id": self.session_id,
            "oai-language": "en-US",
            "oai-client-version": DEFAULT_OAI_CLIENT_VERSION,
            "oai-client-build-number": DEFAULT_OAI_BUILD,
            "sec-ch-ua": '"Chromium";v="150", "Not A(Brand";v="24", "Google Chrome";v="150"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
        }
        if bearer and self.access_token:
            h["Authorization"] = f"Bearer {self.access_token}"
        if extra:
            h.update(extra)
        return h

    def fetch_access_token(self) -> str:
        cached = _load_token_cache()
        if cached:
            self.access_token = cached
            self.backend = "cache"
            return cached

        errors: list[str] = []
        headers = self._headers()

        for imp in IMPERSONATE_CANDIDATES:
            if not imp:
                continue
            try:
                r = _cffi_get(
                    "https://chatgpt.com/api/auth/session", headers, imp
                )
                ct = (r.headers.get("content-type") or "").lower()
                if r.status_code == 200 and "json" in ct:
                    data = r.json()
                    token = data.get("accessToken") or data.get("access_token")
                    if token:
                        self.access_token = token
                        self.backend = f"curl_cffi:{imp}"
                        self.impersonate = imp
                        exp_at = None
                        if data.get("expires"):
                            try:
                                from datetime import datetime

                                exp_at = datetime.fromisoformat(
                                    str(data["expires"]).replace("Z", "+00:00")
                                ).timestamp()
                            except Exception:
                                exp_at = None
                        _save_token_cache(token, exp_at)
                        return token
                errors.append(f"{imp}:{r.status_code}")
            except Exception as e:
                errors.append(f"{imp}:exc:{e}")

        # Optional headless token harvest (not a Live tab)
        if os.environ.get("BTW_NO_PLAYWRIGHT_AUTH", "").strip() in ("1", "true", "yes"):
            raise RuntimeError(
                "accessToken failed via curl_cffi and playwright auth disabled: "
                + "; ".join(errors[-6:])
            )
        try:
            tok = _playwright_access_token(self.cookie_header)
            self.access_token = tok
            self.backend = "playwright_token_only"
            return tok
        except Exception as e:
            errors.append(f"playwright:{e}")
            raise RuntimeError(
                "accessToken failed (CF). Re-export cookies or install playwright. "
                + "; ".join(errors[-8:])
            ) from e

    def _ensure_token(self) -> None:
        if not self.access_token:
            self.fetch_access_token()

    def _get_text(self, url: str, *, bearer: bool = True) -> tuple[int, str, dict[str, str]]:
        """GET url; return status, body text, response headers (lower-case keys)."""
        self._ensure_token()
        headers = self._headers(bearer=bearer)
        imps = [self.impersonate] if self.impersonate else []
        imps += [i for i in IMPERSONATE_CANDIDATES if i and i not in imps]
        last_err = "no impersonate"
        for imp in imps:
            if not imp:
                continue
            try:
                r = _cffi_get(url, headers, imp)
                hdrs = {k.lower(): v for k, v in (r.headers or {}).items()}
                return int(r.status_code), r.text or "", hdrs
            except Exception as e:
                last_err = f"{imp}:{e}"
        try:
            import requests

            r = requests.get(url, headers=headers, timeout=45)
            hdrs = {k.lower(): v for k, v in r.headers.items()}
            return int(r.status_code), r.text or "", hdrs
        except Exception as e:
            raise RuntimeError(f"GET failed {url}: {last_err}; requests:{e}") from e

    def get_conversation(self, conversation_id: str) -> dict[str, Any]:
        """GET /backend-api/conversation/{id} (JSON or base64 body)."""
        from .conversation import decode_conversation_payload, normalize_conversation_id

        cid = normalize_conversation_id(conversation_id)
        url = f"https://chatgpt.com/backend-api/conversation/{cid}"
        status, body, hdrs = self._get_text(url)
        if status != 200:
            raise RuntimeError(
                f"get_conversation HTTP {status} head={body[:180]!r}"
            )
        # HAR sometimes base64-encodes; try decode_conversation_payload either way
        try:
            return decode_conversation_payload(body)
        except ValueError:
            # content-encoding style: pure base64 in body
            if "json" in (hdrs.get("content-type") or ""):
                data = json.loads(body)
                if isinstance(data, dict):
                    return data
            raise

    def list_conversations(
        self, *, offset: int = 0, limit: int = 28
    ) -> list[dict[str, Any]]:
        """Best-effort conversation list; empty list if endpoint shape unknown."""
        candidates = [
            (
                "https://chatgpt.com/backend-api/conversations"
                f"?offset={offset}&limit={limit}&order=updated"
            ),
            (
                "https://chatgpt.com/backend-api/conversations"
                f"?offset={offset}&limit={limit}"
            ),
        ]
        for url in candidates:
            try:
                status, body, _ = self._get_text(url)
            except Exception:
                continue
            if status != 200 or not body:
                continue
            try:
                data = json.loads(body)
            except Exception:
                continue
            items: list[Any]
            if isinstance(data, list):
                items = data
            elif isinstance(data, dict):
                items = (
                    data.get("items")
                    or data.get("conversations")
                    or data.get("data")
                    or []
                )
            else:
                items = []
            out: list[dict[str, Any]] = []
            for it in items:
                if isinstance(it, dict):
                    out.append(it)
            if out:
                return out
        return []

    def find_conversation_by_voice_session(
        self, voice_session_id: str, *, max_scan: int = 12
    ) -> str | None:
        """Scan recent conversations for a matching voice_session_id in mapping."""
        from .conversation import extract_voice_turns

        vid = (voice_session_id or "").strip()
        if not vid:
            return None
        items = self.list_conversations(limit=max_scan)
        for it in items:
            cid = str(
                it.get("id")
                or it.get("conversation_id")
                or it.get("conversationId")
                or ""
            ).strip()
            if not cid:
                continue
            try:
                conv = self.get_conversation(cid)
            except Exception:
                continue
            for turn in extract_voice_turns(conv):
                if (turn.get("voice_session_id") or "").upper() == vid.upper():
                    return str(conv.get("conversation_id") or cid)
            # also check raw mapping metadata quickly
            mapping = conv.get("mapping") or {}
            if isinstance(mapping, dict):
                blob = json.dumps(mapping)
                if vid in blob or vid.upper() in blob:
                    return str(conv.get("conversation_id") or cid)
        return None

    def mint_realtime(self, sdp_offer: str, session_payload: dict[str, Any]) -> str:
        self._ensure_token()

        files = {
            "sdp": (None, sdp_offer),
            "session": (None, json.dumps(session_payload, separators=(",", ":"))),
        }
        headers = self._headers(
            bearer=True,
            extra={
                "x-openai-target-path": "/realtime/wm",
                "x-openai-target-route": "/realtime/wm",
            },
        )
        headers.pop("Content-Type", None)
        headers.pop("content-type", None)

        imps = [self.impersonate] if self.impersonate else []
        imps += [i for i in IMPERSONATE_CANDIDATES if i and i not in imps]

        last_err = None
        for imp in imps:
            if not imp:
                continue
            try:
                r = _cffi_post(
                    "https://chatgpt.com/realtime/wm?dcid=0",
                    headers,
                    files,
                    imp,
                )
                body = r.text or ""
                if r.status_code in (200, 201) and "v=0" in body:
                    self.backend = f"mint:curl_cffi:{imp}"
                    return body
                last_err = f"{imp}:HTTP {r.status_code} head={body[:180]!r}"
            except Exception as e:
                last_err = f"{imp}:exc:{e}"

        # requests fallback with bearer (sometimes works if CF only gates session)
        try:
            import requests

            r = requests.post(
                "https://chatgpt.com/realtime/wm?dcid=0",
                headers=headers,
                files=files,
                timeout=60,
            )
            body = r.text or ""
            if r.status_code in (200, 201) and "v=0" in body:
                self.backend = "mint:requests"
                return body
            last_err = f"requests:HTTP {r.status_code} head={body[:180]!r}"
        except Exception as e:
            last_err = f"requests:exc:{e}"

        raise RuntimeError(f"mint failed: {last_err}")
