"""Outbound proxy for ChatGPT HTTP (token, mint, conversation).

Default: env BTW_PROXY / HTTP(S)_PROXY / ALL_PROXY, else Windows system
proxy (WinINET) as socks5h — matches v2rayN/xray local SOCKS.

Persisted preference (data_dir/proxy.json) from /btw-proxy:
  mode=auto | off | on
  url optional when mode=on

WebRTC media (aiortc) is NOT routed here; use OS TUN if media must go via proxy.
"""
from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from typing import Any
from urllib.parse import urlparse

from .paths import data_dir


def _normalize(raw: str) -> str | None:
    s = (raw or "").strip().strip('"').strip("'")
    if not s or s.lower() in ("0", "none", "off", "direct", "false"):
        return None
    # host:port → socks5h (DNS via proxy)
    if "://" not in s:
        s = f"socks5h://{s}"
    return s


def preference_path():
    return data_dir() / "proxy.json"


def load_preference() -> dict[str, Any]:
    p = preference_path()
    if not p.is_file():
        return {"mode": "auto", "url": None}
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {"mode": "auto", "url": None}
    if not isinstance(raw, dict):
        return {"mode": "auto", "url": None}
    mode = str(raw.get("mode") or "auto").strip().lower()
    if mode not in ("auto", "off", "on"):
        mode = "auto"
    url = raw.get("url")
    url = str(url).strip() if url else None
    if url:
        url = _normalize(url)
    return {"mode": mode, "url": url}


def save_preference(mode: str, url: str | None = None) -> dict[str, Any]:
    mode = (mode or "auto").strip().lower()
    if mode not in ("auto", "off", "on"):
        raise ValueError("mode must be auto|off|on")
    prev = load_preference()
    norm_url = _normalize(url) if url else None
    if mode in ("on", "auto") and not norm_url:
        norm_url = prev.get("url")  # keep last url for re-on
    if mode == "off":
        # keep last url on disk so /btw-proxy on restores
        norm_url = prev.get("url") if not url else norm_url
    data_dir().mkdir(parents=True, exist_ok=True)
    payload = {"mode": mode, "url": norm_url}
    preference_path().write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    clear_proxy_cache()
    # Process-local: file mode is source of truth; clear shell BTW_PROXY so it cannot fight pref
    os.environ.pop("BTW_PROXY", None)
    return load_preference()


def set_proxy(action: str, url: str | None = None) -> dict[str, Any]:
    """Slash/MCP control. action: status|on|off|auto|toggle. url optional for on."""
    act = (action or "status").strip().lower()
    if act in ("", "status", "show", "get"):
        return proxy_info()
    if act in ("off", "0", "direct", "disable", "disabled"):
        save_preference("off")
        return {**proxy_info(), "ok": True, "action": "off"}
    if act in ("auto", "system", "default"):
        save_preference("auto")
        return {**proxy_info(), "ok": True, "action": "auto"}
    if act in ("on", "enable", "enabled"):
        u = (url or "").strip() or None
        if not u:
            prev = load_preference()
            u = prev.get("url")
        if not u:
            # turn on with system/env resolution but pin mode=on via empty url
            # resolve will use wininet; store mode on without url
            data_dir().mkdir(parents=True, exist_ok=True)
            preference_path().write_text(
                json.dumps({"mode": "on", "url": None}, indent=2) + "\n",
                encoding="utf-8",
            )
            clear_proxy_cache()
            os.environ.pop("BTW_PROXY", None)
            info = proxy_info()
            if not info.get("enabled"):
                return {
                    **info,
                    "ok": False,
                    "action": "on",
                    "error": "no proxy URL and system proxy not detected — pass url (e.g. socks5h://127.0.0.1:10808)",
                }
            return {**info, "ok": True, "action": "on"}
        save_preference("on", u)
        return {**proxy_info(), "ok": True, "action": "on"}
    if act in ("toggle", "flip"):
        cur = load_preference()
        if cur.get("mode") == "off" or not resolve_proxy_url():
            return set_proxy("on", url)
        return set_proxy("off")
    # bare url as action
    if "://" in act or re.match(r"^[\w.-]+:\d+$", act):
        save_preference("on", act)
        return {**proxy_info(), "ok": True, "action": "on"}
    return {
        **proxy_info(),
        "ok": False,
        "error": f"unknown action {action!r} — use status|on|off|auto|toggle",
    }


def _wininet_proxy() -> str | None:
    if os.name != "nt":
        return None
    try:
        import winreg

        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
        )
        enable, _ = winreg.QueryValueEx(key, "ProxyEnable")
        if not int(enable or 0):
            return None
        server, _ = winreg.QueryValueEx(key, "ProxyServer")
        server = str(server or "").strip()
        if not server:
            return None
        # "socks=127.0.0.1:10808;http=..." or plain "127.0.0.1:10808"
        if "=" in server:
            parts = {}
            for chunk in server.split(";"):
                if "=" in chunk:
                    k, v = chunk.split("=", 1)
                    parts[k.strip().lower()] = v.strip()
            for key_name in ("socks", "socks5", "https", "http"):
                if parts.get(key_name):
                    host = parts[key_name]
                    if key_name.startswith("socks"):
                        return _normalize(f"socks5h://{host}")
                    return _normalize(f"http://{host}")
            return None
        # bare host:port — system SOCKS (v2rayN default on this machine)
        scheme = (os.environ.get("BTW_PROXY_SCHEME") or "socks5h").strip()
        if "://" in scheme:
            scheme = scheme.split("://", 1)[0]
        return _normalize(f"{scheme}://{server}")
    except Exception:
        return None


def _env_chain_url() -> str | None:
    force = (os.environ.get("BTW_PROXY") or "").strip()
    if force.lower() in ("0", "none", "off", "direct", "false"):
        return None
    if force:
        return _normalize(force)
    for key in (
        "HTTPS_PROXY",
        "HTTP_PROXY",
        "ALL_PROXY",
        "https_proxy",
        "http_proxy",
        "all_proxy",
    ):
        v = (os.environ.get(key) or "").strip()
        if v:
            return _normalize(v)
    return None


@lru_cache(maxsize=1)
def resolve_proxy_url() -> str | None:
    """Return proxy URL or None for direct.

    Order:
      1. pref mode=off → direct
      2. pref mode=on + stored url → that url
      3. BTW_PROXY / HTTP(S)_PROXY env (when not mode=off)
      4. pref mode=on without url, or auto → WinINET system proxy
    """
    pref = load_preference()
    mode = pref.get("mode") or "auto"
    if mode == "off":
        return None
    if mode == "on" and pref.get("url"):
        return str(pref["url"])
    env_u = _env_chain_url()
    if env_u:
        return env_u
    force_raw = (os.environ.get("BTW_PROXY") or "").strip().lower()
    if force_raw in ("0", "none", "off", "direct", "false"):
        return None
    return _wininet_proxy()


def proxy_dict() -> dict[str, str] | None:
    """requests / curl_cffi proxies mapping, or None."""
    url = resolve_proxy_url()
    if not url:
        return None
    return {"http": url, "https": url}


def proxy_info() -> dict[str, Any]:
    pref = load_preference()
    url = resolve_proxy_url()
    if not url:
        return {
            "enabled": False,
            "url": None,
            "mode": pref.get("mode") or "auto",
            "pref_url": pref.get("url"),
            "note": "direct — /btw-proxy on|off|auto  (media always WebRTC direct)",
        }
    try:
        p = urlparse(url)
        host = p.hostname or ""
        port = p.port or ""
        safe = f"{p.scheme}://{host}:{port}" if port else f"{p.scheme}://{host}"
    except Exception:
        safe = re.sub(r"://[^@]+@", "://***@", url)
    return {
        "enabled": True,
        "url": safe,
        "scheme": urlparse(url).scheme if "://" in url else "?",
        "mode": pref.get("mode") or "auto",
        "pref_url": pref.get("url"),
        "note": "HTTP mint/token/hydrate only — WebRTC media is direct unless OS TUN",
    }


def clear_proxy_cache() -> None:
    resolve_proxy_url.cache_clear()
