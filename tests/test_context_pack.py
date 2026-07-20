"""Context pack replace vs append — boot must not inherit stale history."""
from pathlib import Path
import sys
from importlib import reload

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def _reload_btw(tmp_path, monkeypatch):
    monkeypatch.setenv("GROK_PLUGIN_DATA", str(tmp_path))
    import btw.paths as paths
    import btw.sessions_store as store
    import btw.state as state
    import btw.service as service

    reload(paths)
    reload(store)
    reload(state)
    reload(service)
    return service, store


def test_push_context_append_default(tmp_path, monkeypatch):
    service, store = _reload_btw(tmp_path, monkeypatch)
    store.create_session("pack", profile="default", context="old fact")
    out = service.push_context("new fact")
    assert out["appended"] is True
    assert out["replaced"] is False
    assert "old fact" in store.get_active().context
    assert "new fact" in store.get_active().context
    assert out["context_chars"] > len("new fact")


def test_push_context_replace(tmp_path, monkeypatch):
    service, store = _reload_btw(tmp_path, monkeypatch)
    store.create_session("pack", profile="default", context="stale history dump")
    out = service.push_context("clean session brief", append=False)
    assert out["appended"] is False
    assert out["replaced"] is True
    assert store.get_active().context == "clean session brief"
    assert "stale" not in store.get_active().context


def test_start_context_replaces_pack(tmp_path, monkeypatch):
    service, store = _reload_btw(tmp_path, monkeypatch)
    store.create_session("pack", profile="default", context="ancient btw inject test noise")

    # Avoid real runtime / cookies: stop at pack write by stubbing spawn + cookies.
    monkeypatch.setattr(service, "_pid_running", lambda: False)
    monkeypatch.setattr(
        service,
        "start_background",
        lambda **kw: {"ok": True, "pid": 1, "viz": {"ok": True}},
    )

    class _Cookie:
        @staticmethod
        def load_cookie_header():
            return "ok"

    monkeypatch.setattr(service, "cookie_mod", _Cookie)

    out = service.start(context="Grok session: skills cleanup; awaiting go.")
    assert out.get("context_replaced") is True
    assert store.get_active().context == "Grok session: skills cleanup; awaiting go."
    assert "ancient" not in store.get_active().context
    assert out.get("context_chars") == len("Grok session: skills cleanup; awaiting go.")


def test_start_without_context_keeps_pack(tmp_path, monkeypatch):
    service, store = _reload_btw(tmp_path, monkeypatch)
    store.create_session("pack", profile="default", context="keep me")
    monkeypatch.setattr(service, "_pid_running", lambda: False)
    monkeypatch.setattr(
        service,
        "start_background",
        lambda **kw: {"ok": True, "pid": 1, "viz": {"ok": True}},
    )

    class _Cookie:
        @staticmethod
        def load_cookie_header():
            return "ok"

    monkeypatch.setattr(service, "cookie_mod", _Cookie)

    out = service.start()
    assert out.get("context_replaced") is False
    assert store.get_active().context == "keep me"
