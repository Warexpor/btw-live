"""High-level /btw-vc control for Grok Build."""
from __future__ import annotations

import json
import uuid
from typing import Any

from . import cookies as cookie_mod
from . import sessions_store as ss
from .control import push_command, status_live_path
from .paths import data_dir
from .profiles import list_profiles, load_profile
from .runtime import doctor as runtime_doctor
from .runtime import (
    start_background,
    start_viz,
    stop_runtime,
    stop_viz,
    _pid_running,
    _viz_pid_running,
    log_path,
)
from .session_json import build_voice_session_payload, instruction_events
from .state import (
    load_state,
    mark_error,
    mark_starting,
    mark_stopped,
    save_state,
    set_context,
)
from .version import __version__
from .voices import list_voices


def status() -> dict[str, Any]:
    st = load_state()
    active = ss.get_active()
    cookie_ok = False
    cookie_err = None
    try:
        ch = cookie_mod.load_cookie_header()
        cookie_ok = bool(ch and "session-token" in ch)
    except Exception as e:
        cookie_err = str(e)

    live = None
    if status_live_path().is_file():
        try:
            live = json.loads(status_live_path().read_text(encoding="utf-8"))
        except Exception:
            live = None

    # Dead runtime + leftover live_status.json must not look "live"
    running = _pid_running()
    if live and not running and str(live.get("status") or "").lower() == "live":
        live = {**live, "status": "stopped", "stale": True}

    eff_voice = ss.effective_voice(active)
    return {
        "version": __version__,
        "state": st.to_dict(),
        "active_session": {
            "id": active.id,
            "name": active.name,
            "profile": active.profile,
            "voice": active.voice or None,
            "voice_effective": eff_voice,
            "context_chars": len(active.context or ""),
            "context_preview": (active.context or "")[:120].replace("\n", " "),
        },
        "sessions": ss.list_sessions(),
        "profiles": list_profiles(),
        "voices": list_voices(),
        "cookies_ok": cookie_ok,
        "cookies_error": cookie_err,
        "runtime_pid_running": running,
        "viz_running": _viz_pid_running(),
        "muted": bool(st.muted or (live or {}).get("muted")),
        "live": live,
        "data_dir": str(data_dir()),
        "runtime_log": str(log_path()),
    }


def session_list() -> dict[str, Any]:
    return {"ok": True, "sessions": ss.list_sessions(), "active": ss.get_active().to_dict()}


def session_new(
    name: str,
    profile: str = "default",
    context: str = "",
    voice: str = "",
) -> dict[str, Any]:
    s = ss.create_session(name, profile=profile, context=context, voice=voice)
    st = load_state()
    st.profile = s["profile"]
    st.session_name = s["name"]
    st.session_id = s["id"]
    set_context(st, s.get("context") or "")
    return {
        "ok": True,
        "session": s,
        "voice_effective": ss.effective_voice(ss.get_active()),
    }


def list_tts_voices() -> dict[str, Any]:
    active = ss.get_active()
    return {
        "ok": True,
        "voices": list_voices(),
        "active_session": active.name,
        "session_voice": active.voice or None,
        "voice_effective": ss.effective_voice(active),
        "note": "Set with btw_set_voice. Applies on next /btw-vc start (not mid-call).",
    }


def set_voice(voice: str) -> dict[str, Any]:
    """Set speak voice on active session (mint field). Requires restart if already live."""
    s = ss.update_active(voice=voice)
    return {
        "ok": True,
        "session": s["name"],
        "voice": s.get("voice") or None,
        "voice_effective": ss.effective_voice(ss.get_active()),
        "live": _pid_running(),
        "hint": "Voice is fixed at mint — stop and /btw-vc again to apply if live.",
    }


def session_use(id_or_name: str) -> dict[str, Any]:
    s = ss.use_session(id_or_name)
    st = load_state()
    st.profile = s["profile"]
    st.session_name = s["name"]
    st.session_id = s["id"]
    set_context(st, s.get("context") or "")
    return {"ok": True, "session": s}


def session_delete(id_or_name: str) -> dict[str, Any]:
    return ss.delete_session(id_or_name)


def set_profile(name: str) -> dict[str, Any]:
    load_profile(name)
    s = ss.update_active(profile=name)
    st = load_state()
    st.profile = name
    save_state(st)
    return {"ok": True, "profile": name, "session": s, "profiles": list_profiles()}


def push_context(context: str, *, append: bool = True) -> dict[str, Any]:
    """Update active session context pack. Live: audio top-up (+ DC best-effort).

    Default append=True so mid-call /btw-topup adds facts instead of wiping the pack.
    """
    active = ss.get_active()
    delta = (context or "").strip()
    prior = (active.context or "").strip()
    if append and prior and delta:
        full = prior + "\n\n" + delta
    else:
        full = delta

    s = ss.update_active(context=full)
    st = load_state()
    set_context(st, full)
    prof = load_profile(s["profile"])
    instructions = prof.assemble_instructions(full)
    (data_dir() / "instructions.txt").write_text(instructions, encoding="utf-8")
    (data_dir() / "context.txt").write_text(full, encoding="utf-8")
    st.instructions_chars = len(instructions)
    save_state(st)

    live_ok = False
    if _pid_running():
        # Speak delta; pass full_context so runtime pack stays consistent
        push_command(
            "push_context",
            context=delta,
            full_context=full,
            instructions=instructions,
        )
        live_ok = True

    return {
        "ok": True,
        "context_chars": len(full),
        "delta_chars": len(delta),
        "appended": bool(append and prior and delta),
        "instructions_chars": len(instructions),
        "preview": full[:240].replace("\n", " "),
        "session": s["name"],
        "live_push_queued": live_ok,
    }


def preview_instructions(
    profile: str | None = None, context: str | None = None
) -> dict[str, Any]:
    active = ss.get_active()
    name = profile or active.profile
    prof = load_profile(name)
    if context is None:
        context = active.context or ""
    instructions = prof.assemble_instructions(context)
    return {
        "profile": prof.name,
        "session": active.name,
        "voice": prof.voice,
        "voice_mode": prof.voice_mode,
        "instructions_chars": len(instructions),
        "instructions": instructions,
        "session_payload": build_voice_session_payload(prof),
        "instruction_events": instruction_events(instructions),
        "how_it_works": (
            "Profile system prompt + channel contract + session context "
            "→ written to instructions.txt → on DC open, session.update + "
            "bootstrap user item (btw brief). Mid-call: push_context queues DC update."
        ),
    }


def prepare_start(profile: str | None = None) -> dict[str, Any]:
    active = ss.get_active()
    name = profile or active.profile
    try:
        prof = load_profile(name)
    except Exception as e:
        st = load_state()
        mark_error(st, str(e))
        return {"ok": False, "error": str(e)}

    st = load_state()
    mark_starting(st, name)
    context = active.context or ""
    if profile and profile != active.profile:
        ss.update_active(profile=profile)
        context = ss.get_active().context or ""
    instructions = prof.assemble_instructions(context)
    voice_id = str(uuid.uuid4()).upper()
    speak = ss.effective_voice(active)
    session_payload = build_voice_session_payload(
        prof, voice_session_id=voice_id, voice=speak
    )

    (data_dir() / "context.txt").write_text(context, encoding="utf-8")
    (data_dir() / "instructions.txt").write_text(instructions, encoding="utf-8")
    slim = {
        "profile": prof.name,
        "session_name": active.name,
        "voice": speak,
        "voice_session_id": voice_id,
        "instructions_chars": len(instructions),
        "context_chars": len(context),
        "session": session_payload,
    }
    (data_dir() / "last_prepare.json").write_text(json.dumps(slim, indent=2), encoding="utf-8")

    st.voice_session_id = voice_id
    st.instructions_chars = len(instructions)
    st.context_chars = len(context)
    st.session_name = active.name
    st.session_id = active.id
    st.profile = prof.name
    st.status = "prepared"
    save_state(st)
    return {"ok": True, **slim, "state": st.to_dict()}


def start(
    profile: str | None = None,
    context: str | None = None,
    use_mic: bool = True,
    muted: bool = False,
) -> dict[str, Any]:
    if _pid_running():
        return {"ok": False, "error": "already live — stop first", "status": status()}

    if context is not None:
        push_context(context)
    if profile:
        set_profile(profile)

    prep = prepare_start(None)
    if not prep.get("ok"):
        return prep
    try:
        cookie_mod.load_cookie_header()
    except Exception as e:
        st = load_state()
        mark_error(st, str(e))
        return {"ok": False, "error": str(e)}

    active = ss.get_active()
    ss.touch_active_used()
    st = load_state()
    st.muted = bool(muted)
    save_state(st)

    speak = ss.effective_voice(active)
    spawn = start_background(
        profile=active.profile,
        use_mic=use_mic,
        muted=muted,
        session_name=active.name,
        voice=speak,
    )
    return {
        "ok": spawn.get("ok", False),
        "mode": "standalone",
        "session": active.name,
        "profile": active.profile,
        "voice": speak,
        "instructions_chars": prep.get("instructions_chars"),
        "muted": muted,
        "runtime": spawn,
        "viz": spawn.get("viz"),
        "hint": "Speak on mic. Visualizer opens with Live. Mute: btw_mute. Stop: btw_stop.",
    }


def open_viz() -> dict[str, Any]:
    """Open (or re-open) the voice visualizer GUI."""
    out = start_viz(force=False)
    if out.get("already"):
        return {**out, "message": "visualizer already open"}
    return {**out, "message": "visualizer launched" if out.get("ok") else out.get("error")}


def close_viz() -> dict[str, Any]:
    return stop_viz()


def stop() -> dict[str, Any]:
    if _pid_running():
        push_command("stop")
    out = stop_runtime()
    st = load_state()
    mark_stopped(st)
    return out


def mute() -> dict[str, Any]:
    st = load_state()
    st.muted = True
    save_state(st)
    if _pid_running():
        push_command("mute")
        return {"ok": True, "muted": True, "queued": True}
    return {"ok": True, "muted": True, "queued": False, "note": "not live — will apply on next start if state kept"}


def unmute() -> dict[str, Any]:
    st = load_state()
    st.muted = False
    save_state(st)
    if _pid_running():
        push_command("unmute")
        return {"ok": True, "muted": False, "queued": True}
    return {"ok": True, "muted": False, "queued": False}


def reinject() -> dict[str, Any]:
    ip = data_dir() / "instructions.txt"
    instructions = ip.read_text(encoding="utf-8") if ip.is_file() else ""
    if not _pid_running():
        return {"ok": False, "error": "not live"}
    push_command("reinject", instructions=instructions)
    return {"ok": True, "instructions_chars": len(instructions), "queued": True}


def doctor() -> dict[str, Any]:
    d = runtime_doctor()
    d["service"] = status()
    return d


def import_cookies(raw_header: str) -> dict[str, Any]:
    raw = (raw_header or "").strip()
    if not raw or "=" not in raw:
        return {"ok": False, "error": "empty or invalid Cookie header"}
    if _pid_running():
        return {
            "ok": False,
            "error": "Live is running — /btw-stop first, then swap cookies",
        }
    path = cookie_mod.import_cookie_header(raw)
    # quick auth check without dumping secrets
    auth = None
    try:
        from .http_client import ChatGPTClient

        c = ChatGPTClient()
        tok = c.fetch_access_token()
        auth = {"access_token": "ok", "len": len(tok), "backend": c.backend}
    except Exception as e:
        auth = {"access_token": "err", "error": str(e)[:200]}
    return {
        "ok": True,
        "path": str(path),
        "cookie_names": len(raw.split(";")),
        "token_cache_cleared": True,
        "auth": auth,
    }


def clear_cookies() -> dict[str, Any]:
    if _pid_running():
        return {
            "ok": False,
            "error": "Live is running — /btw-stop first, then clear cookies",
        }
    return cookie_mod.clear_cookies()
