"""btw Live surface — modern WebView2 UI (pywebview) with tk fallback.

  python -m btw.viz
  python -m btw.viz --demo
  BTW_VIZ_TK=1  force tkinter shell
"""
from __future__ import annotations

import json
import math
import os
import sys
import time
from pathlib import Path
from typing import Any

from .control import push_command, read_meters, viz_pid_path
from .paths import data_dir
from .version import __version__


def _ui_dir() -> Path:
    return Path(__file__).resolve().parent / "viz_ui"


def _write_pid() -> None:
    data_dir().mkdir(parents=True, exist_ok=True)
    try:
        viz_pid_path().write_text(str(os.getpid()), encoding="utf-8")
    except Exception:
        pass


def _clear_pid() -> None:
    try:
        p = viz_pid_path()
        if p.is_file():
            p.unlink(missing_ok=True)
    except Exception:
        pass


class VizApi:
    """JS bridge: window.pywebview.api.*"""

    def get_meters(self) -> dict[str, Any]:
        return read_meters() or {"status": "idle"}

    def mute(self) -> dict[str, Any]:
        return push_command("mute")

    def unmute(self) -> dict[str, Any]:
        return push_command("unmute")

    def stop(self) -> dict[str, Any]:
        return push_command("stop")

    def version(self) -> str:
        return __version__


def _demo_loop() -> None:
    """Write fake meters so the shell animates without Live.

    Default pattern: AI speaking only (downlink bursts). Mic stays quiet so
    the orb can be judged as AI-driven. Set BTW_VIZ_DEMO_BOTH=1 for old dual.
    """
    from .control import write_meters

    both = os.environ.get("BTW_VIZ_DEMO_BOTH", "").strip() in ("1", "true", "yes")
    t0 = time.time()
    while True:
        t = time.time() - t0
        # speech-like envelope: talk ~2.2s, pause ~0.9s
        cycle = t % 3.1
        talking = cycle < 2.2
        if talking:
            # formant-ish peaks above AI_THRESH (~0.12 level → need raw peaks higher)
            dn = 0.22 + 0.55 * abs(math.sin(t * 9.5)) * (0.55 + 0.45 * abs(math.sin(t * 2.1)))
            dn *= 0.75 + 0.25 * abs(math.sin(t * 0.7))
        else:
            dn = 0.02 + 0.03 * abs(math.sin(t * 3.0))  # below orb threshold

        if both:
            muted = int(t) % 17 > 14
            up = 0.15 + 0.45 * abs(math.sin(t * 2.3))
            injecting = int(t) % 23 > 20
        else:
            muted = False
            up = 0.0  # mic silent — orb must not react
            injecting = False

        write_meters(
            {
                "status": "live",
                "session_name": "demo",
                "profile": "default",
                "voice": "maple",
                "muted": muted,
                "injecting": injecting,
                "uplink_peak": up,
                "downlink_peak": dn,
                "pc": "connected",
                "ice": "connected",
                "dc_open": True,
                "uplink_src": "mic",
            }
        )
        time.sleep(0.05)


def run_webview(*, demo: bool = False) -> int:
    try:
        import webview
    except ImportError as e:
        print(json.dumps({"ok": False, "error": f"pywebview missing: {e}"}), flush=True)
        return 2

    ui = _ui_dir() / "index.html"
    if not ui.is_file():
        print(json.dumps({"ok": False, "error": f"missing UI {ui}"}), flush=True)
        return 2

    if demo:
        import threading

        threading.Thread(target=_demo_loop, daemon=True).start()
    else:
        # ensure idle meters exist so first paint isn't empty
        from .control import write_meters

        if not read_meters():
            write_meters({"status": "idle", "uplink_peak": 0.0, "downlink_peak": 0.0})

    _write_pid()
    api = VizApi()
    # pywebview 6 create_window has no `icon=` kw (that used to force silent tk fallback)
    window = webview.create_window(
        f"btw  ·  live surface  ·  {__version__}",
        url=ui.as_uri(),
        js_api=api,
        width=1080,
        height=420,
        min_size=(820, 340),
        background_color="#0a0a0a",
        text_select=False,
        confirm_close=False,
        on_top=True,
    )

    def _on_closed():
        _clear_pid()

    try:
        window.events.closed += _on_closed
    except Exception:
        pass

    # pywebview 6: icon goes on start(), not create_window()
    icon = Path(__file__).resolve().parent / "assets" / "icon.ico"
    if not icon.is_file():
        icon = Path(__file__).resolve().parent / "assets" / "icon.png"
    start_kwargs: dict[str, Any] = {
        "debug": bool(os.environ.get("BTW_VIZ_DEBUG")),
    }
    if icon.is_file():
        start_kwargs["icon"] = str(icon)
    webview.start(**start_kwargs)
    _clear_pid()
    return 0


def run_tk(*, demo: bool = False) -> int:
    if demo:
        import threading

        threading.Thread(target=_demo_loop, daemon=True).start()
    from . import viz_tk

    return viz_tk.main([])


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    demo = "--demo" in args or os.environ.get("BTW_VIZ_DEMO", "").strip() in (
        "1",
        "true",
        "yes",
    )
    force_tk = "--tk" in args or os.environ.get("BTW_VIZ_TK", "").strip() in (
        "1",
        "true",
        "yes",
    )

    if force_tk:
        return run_tk(demo=demo)

    try:
        import webview  # noqa: F401
    except ImportError:
        print(
            json.dumps(
                {
                    "ok": False,
                    "fallback": "tk",
                    "hint": "pip install pywebview — using tk shell",
                }
            ),
            flush=True,
        )
        return run_tk(demo=demo)

    try:
        return run_webview(demo=demo)
    except Exception as e:
        # Log hard — pythonw swallows stdout; never hide webview death as "tk is fine"
        err = {"ok": False, "error": str(e), "fallback": "tk"}
        print(json.dumps(err), flush=True)
        try:
            logp = data_dir() / "viz.log"
            with logp.open("a", encoding="utf-8") as f:
                f.write(json.dumps(err) + "\n")
        except Exception:
            pass
        # Prefer dying loud over silent tk unless explicitly allowed
        if os.environ.get("BTW_VIZ_ALLOW_TK", "").strip() in ("1", "true", "yes"):
            return run_tk(demo=demo)
        raise


if __name__ == "__main__":
    raise SystemExit(main())
