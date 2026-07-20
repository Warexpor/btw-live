"""Proxy resolve — env, pref file, normalize (no network)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from btw.proxy import (
    clear_proxy_cache,
    load_preference,
    proxy_dict,
    proxy_info,
    resolve_proxy_url,
    save_preference,
    set_proxy,
)


@pytest.fixture(autouse=True)
def _iso_pref(tmp_path, monkeypatch):
    monkeypatch.setenv("GROK_PLUGIN_DATA", str(tmp_path))
    for k in (
        "BTW_PROXY",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
        "CLAUDE_PLUGIN_DATA",
    ):
        monkeypatch.delenv(k, raising=False)
    clear_proxy_cache()
    yield
    clear_proxy_cache()


def test_btw_proxy_off(monkeypatch):
    monkeypatch.setenv("BTW_PROXY", "0")
    assert resolve_proxy_url() is None
    assert proxy_dict() is None
    assert proxy_info()["enabled"] is False


def test_btw_proxy_socks(monkeypatch):
    monkeypatch.setenv("BTW_PROXY", "socks5://127.0.0.1:10808")
    assert resolve_proxy_url() == "socks5://127.0.0.1:10808"
    d = proxy_dict()
    assert d is not None
    assert d["https"].startswith("socks5://")
    info = proxy_info()
    assert info["enabled"] is True
    assert "10808" in (info.get("url") or "")


def test_host_port_becomes_socks5h(monkeypatch):
    monkeypatch.setenv("BTW_PROXY", "127.0.0.1:10808")
    assert resolve_proxy_url() == "socks5h://127.0.0.1:10808"


def test_https_proxy_env(monkeypatch):
    monkeypatch.delenv("BTW_PROXY", raising=False)
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:7890")
    assert resolve_proxy_url() == "http://127.0.0.1:7890"


def test_pref_off_beats_env(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:7890")
    save_preference("off")
    assert resolve_proxy_url() is None
    assert load_preference()["mode"] == "off"


def test_set_proxy_on_off_toggle():
    out = set_proxy("on", "socks5h://127.0.0.1:10808")
    assert out.get("ok") is True
    assert out.get("enabled") is True
    assert "10808" in (out.get("url") or "")
    out = set_proxy("off")
    assert out.get("enabled") is False
    assert out.get("mode") == "off"
    out = set_proxy("toggle")
    assert out.get("enabled") is True
    out = set_proxy("status")
    assert "mode" in out
