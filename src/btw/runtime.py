"""btw Live runtime CLI — standalone (no browser tab).

  python -m btw.runtime doctor
  python -m btw.runtime start --profile default
  python -m btw.runtime run --profile default [--seconds N] [--no-mic]
  python -m btw.runtime stop
  python -m btw.runtime mint-smoke   # auth+mint only (silent, short)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from . import cookies as cookie_mod
from .paths import data_dir, plugin_root, python_exe
from .profiles import load_profile
from .state import load_state, mark_error, mark_live, mark_starting, mark_stopped, save_state
from .version import __version__


def log_path() -> Path:
    return data_dir() / "runtime.log"


def pid_path() -> Path:
    return data_dir() / "runtime.pid"


def _log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {msg}"
    print(line, flush=True)
    try:
        with log_path().open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def doctor() -> dict[str, Any]:
    out: dict[str, Any] = {
        "version": __version__,
        "python": sys.version.split()[0],
        "data_dir": str(data_dir()),
        "plugin_root": str(plugin_root()),
        "mode": "standalone",
    }
    try:
        out["python_exe"] = python_exe()
        out["python_exe_ok"] = True
        out["python_is_hermes"] = "hermes" in out["python_exe"].lower()
    except Exception as e:
        out["python_exe"] = None
        out["python_exe_ok"] = False
        out["python_exe_error"] = str(e)
        out["python_is_hermes"] = "hermes" in sys.executable.lower()
    for mod in ("curl_cffi", "aiortc", "av", "sounddevice", "numpy"):
        try:
            __import__(mod)
            out[mod] = "ok"
        except Exception as e:
            out[mod] = f"missing: {e}"

    try:
        ch = cookie_mod.load_cookie_header()
        out["cookies"] = "ok" if "session-token" in ch else "no_session_token"
        out["cookie_len"] = len(ch)
    except Exception as e:
        out["cookies"] = f"err: {e}"

    # quick auth probe
    try:
        from .http_client import ChatGPTClient

        c = ChatGPTClient()
        tok = c.fetch_access_token()
        out["access_token"] = f"ok len={len(tok)} backend={c.backend}"
    except Exception as e:
        out["access_token"] = f"err: {e}"

    st = load_state()
    out["state"] = st.to_dict()
    out["pid_running"] = _pid_running()
    return out


def _pid_running() -> bool:
    p = pid_path()
    if not p.is_file():
        return False
    try:
        pid = int(p.read_text(encoding="utf-8").strip())
    except Exception:
        return False
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel32.OpenProcess(0x1000, 0, pid)
        if handle:
            kernel32.CloseHandle(handle)
            return True
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def stop_runtime() -> dict[str, Any]:
    st = load_state()
    killed = False
    if pid_path().is_file():
        try:
            pid = int(pid_path().read_text(encoding="utf-8").strip())
            if sys.platform == "win32":
                subprocess.run(
                    ["taskkill", "/PID", str(pid), "/T", "/F"],
                    capture_output=True,
                    text=True,
                )
            else:
                os.kill(pid, signal.SIGTERM)
            killed = True
        except Exception as e:
            _log(f"stop err: {e}")
        try:
            pid_path().unlink(missing_ok=True)
        except Exception:
            pass
    mark_stopped(st)
    return {"ok": True, "killed": killed, "state": load_state().to_dict()}


def _load_instructions(profile_name: str) -> tuple[Any, str]:
    prof = load_profile(profile_name)
    ctx_path = data_dir() / "context.txt"
    context = ctx_path.read_text(encoding="utf-8") if ctx_path.is_file() else ""
    instructions = prof.assemble_instructions(context)
    (data_dir() / "instructions.txt").write_text(instructions, encoding="utf-8")
    return prof, instructions


def start_foreground(
    profile: str | None = None,
    *,
    use_mic: bool = True,
    seconds: float | None = None,
    muted: bool = False,
    session_name: str = "default",
    voice: str | None = None,
) -> dict[str, Any]:
    st = load_state()
    name = profile or st.profile or "default"
    mark_starting(st, name)
    try:
        prof, instructions = _load_instructions(name)
    except Exception as e:
        mark_error(st, str(e))
        return {"ok": False, "error": str(e)}

    from .live_session import LiveSession
    from .voices import normalize_voice

    speak = normalize_voice(voice) if voice else prof.voice
    ctx_path = data_dir() / "context.txt"
    context = ctx_path.read_text(encoding="utf-8") if ctx_path.is_file() else ""

    async def _run() -> dict[str, Any]:
        sess = LiveSession(
            prof,
            instructions,
            use_mic=use_mic,
            muted=muted or st.muted,
            session_name=session_name or st.session_name or "default",
            voice=speak,
            context=context,
        )
        try:
            stats = await sess.start()
            mark_live(st, sess.voice_session_id, len(instructions))
            st.notes = [
                f"mint={stats.get('mint')} mic={stats.get('mic')} "
                f"pc={stats.get('pc_state')}"
            ]
            save_state(st)
            return await sess.run_until_stopped(seconds=seconds)
        except Exception as e:
            mark_error(st, str(e))
            await sess.stop()
            raise

    try:
        stats = asyncio.run(_run())
        mark_stopped(load_state())
        return {"ok": True, **stats}
    except Exception as e:
        _log(f"fatal: {e}")
        mark_error(load_state(), str(e))
        return {"ok": False, "error": str(e)}


def mint_smoke() -> dict[str, Any]:
    """Auth + mint + short connect (silent, 8s) for CI/smoke."""
    return start_foreground("default", use_mic=False, seconds=8.0)


def start_background(
    profile: str | None = None,
    *,
    use_mic: bool = True,
    seconds: float | None = None,
    muted: bool = False,
    session_name: str = "default",
    voice: str | None = None,
) -> dict[str, Any]:
    if _pid_running():
        return {"ok": False, "error": "already running", "pid_running": True}

    data_dir().mkdir(parents=True, exist_ok=True)
    try:
        py = python_exe()
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}

    env = os.environ.copy()
    env["PYTHONPATH"] = str(plugin_root() / "src") + os.pathsep + env.get("PYTHONPATH", "")
    env["PYTHONUNBUFFERED"] = "1"
    env["BTW_PYTHON"] = py
    cmd = [
        py,
        "-u",
        "-m",
        "btw.runtime",
        "run",
        "--profile",
        profile or load_state().profile or "default",
        "--session-name",
        session_name or "default",
    ]
    if voice:
        cmd.extend(["--voice", voice])
    if not use_mic:
        cmd.append("--no-mic")
    if muted:
        cmd.append("--muted")
    if seconds is not None:
        cmd.extend(["--seconds", str(seconds)])

    # Open log in child via redirection; never inherit MCP stdin (hangs on Windows).
    logf = log_path().open("a", encoding="utf-8", buffering=1)
    if sys.platform == "win32":
        # DETACHED_PROCESS (0x8) hangs child on Windows (~5MB, no log).
        # CREATE_NO_WINDOW + DEVNULL stdin keeps redirected stdout working.
        CREATE_NEW_PROCESS_GROUP = 0x00000200
        CREATE_NO_WINDOW = 0x08000000
        proc = subprocess.Popen(
            cmd,
            cwd=str(plugin_root()),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=logf,
            stderr=subprocess.STDOUT,
            creationflags=CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW,
            close_fds=False,
        )
    else:
        proc = subprocess.Popen(
            cmd,
            cwd=str(plugin_root()),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=logf,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    try:
        logf.write(f"\n--- spawn pid={proc.pid} py={py} ---\n")
        logf.flush()
    except Exception:
        pass
    pid_path().write_text(str(proc.pid), encoding="utf-8")
    st = load_state()
    st.status = "starting"
    st.profile = profile or st.profile
    st.session_name = session_name or st.session_name
    st.muted = bool(muted)
    st.notes = [f"pid={proc.pid}", "mode=standalone"]
    save_state(st)
    return {
        "ok": True,
        "pid": proc.pid,
        "log": str(log_path()),
        "profile": profile or st.profile,
        "mode": "standalone",
        "message": "standalone Live runtime spawned — mic/speakers on this machine",
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="btw.runtime")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_run = sub.add_parser("run", help="foreground Live session (standalone)")
    p_run.add_argument("--profile", default=None)
    p_run.add_argument("--session-name", default="default")
    p_run.add_argument("--voice", default=None)
    p_run.add_argument("--no-mic", action="store_true")
    p_run.add_argument("--muted", action="store_true")
    p_run.add_argument("--seconds", type=float, default=None)

    p_start = sub.add_parser("start", help="background Live session")
    p_start.add_argument("--profile", default=None)
    p_start.add_argument("--session-name", default="default")
    p_start.add_argument("--voice", default=None)
    p_start.add_argument("--no-mic", action="store_true")
    p_start.add_argument("--muted", action="store_true")
    p_start.add_argument("--seconds", type=float, default=None)

    sub.add_parser("stop")
    sub.add_parser("doctor")
    sub.add_parser("mint-smoke", help="auth+mint+8s silent connect")

    args = ap.parse_args(argv)

    if args.cmd == "doctor":
        print(json.dumps(doctor(), indent=2))
        return 0
    if args.cmd == "stop":
        print(json.dumps(stop_runtime(), indent=2))
        return 0
    if args.cmd == "mint-smoke":
        pid_path().write_text(str(os.getpid()), encoding="utf-8")
        out = mint_smoke()
        print(json.dumps(out, indent=2, default=str))
        return 0 if out.get("ok") else 1
    if args.cmd == "start":
        print(
            json.dumps(
                start_background(
                    args.profile,
                    use_mic=not args.no_mic,
                    seconds=args.seconds,
                    muted=bool(args.muted),
                    session_name=args.session_name or "default",
                    voice=args.voice,
                ),
                indent=2,
            )
        )
        return 0
    if args.cmd == "run":
        pid_path().write_text(str(os.getpid()), encoding="utf-8")
        out = start_foreground(
            args.profile,
            use_mic=not args.no_mic,
            seconds=args.seconds,
            muted=bool(args.muted),
            session_name=args.session_name or "default",
            voice=args.voice,
        )
        print(json.dumps(out, indent=2, default=str))
        return 0 if out.get("ok") else 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
