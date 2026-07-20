#!/usr/bin/env python3
"""Stdio MCP server for btw-vc."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from btw import service  # noqa: E402
from btw.version import __version__  # noqa: E402


def respond(msg_id, result=None, error=None):
    body = {"jsonrpc": "2.0", "id": msg_id}
    if error is not None:
        body["error"] = error
    else:
        body["result"] = result
    sys.stdout.write(json.dumps(body) + "\n")
    sys.stdout.flush()


def _ok(result: dict) -> dict:
    return {"content": [{"type": "text", "text": json.dumps(result, indent=2)}]}


def _err(msg: str) -> dict:
    return {"isError": True, "content": [{"type": "text", "text": msg}]}


TOOLS = [
    {
        "name": "btw_status",
        "description": "Status: active session, muted, live runtime, cookies.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "btw_doctor",
        "description": "Diagnose btw-vc install and auth.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "btw_session_list",
        "description": "List named voice sessions (profile + context packs).",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "btw_session_new",
        "description": "Create a named voice session and make it active.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "profile": {"type": "string"},
                "context": {"type": "string"},
                "voice": {"type": "string"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "btw_session_use",
        "description": "Switch active voice session by id or name.",
        "inputSchema": {
            "type": "object",
            "properties": {"id_or_name": {"type": "string"}},
            "required": ["id_or_name"],
        },
    },
    {
        "name": "btw_session_delete",
        "description": "Delete a voice session by id or name.",
        "inputSchema": {
            "type": "object",
            "properties": {"id_or_name": {"type": "string"}},
            "required": ["id_or_name"],
        },
    },
    {
        "name": "btw_session_bind",
        "description": "Bind active /btw-vc session to a ChatGPT conversation_id (uuid or chatgpt.com URL). Next start resumes that thread.",
        "inputSchema": {
            "type": "object",
            "properties": {"conversation_id": {"type": "string"}},
            "required": ["conversation_id"],
        },
    },
    {
        "name": "btw_session_fresh",
        "description": "Clear ChatGPT conversation bind on active session (keep local pack). Next start is unbound.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "btw_session_sync",
        "description": "Fetch bound ChatGPT conversation (title, turn preview, resume snip). No Live start.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "btw_set_profile",
        "description": "Set profile on active session (default|debugger|architect).",
        "inputSchema": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
    },
    {
        "name": "btw_list_voices",
        "description": "List available Live speak voices and current effective voice.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "btw_set_voice",
        "description": "Set speak voice on active session (e.g. maple, sol, sage). Applies on next start.",
        "inputSchema": {
            "type": "object",
            "properties": {"voice": {"type": "string"}},
            "required": ["voice"],
        },
    },
    {
        "name": "btw_push_context",
        "description": (
            "Update context pack on active session. Default append=true (mid-call top-up: "
            "append + uplink TTS delta). append=false replaces the pack. If live, queues inject."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "context": {"type": "string"},
                "append": {
                    "type": "boolean",
                    "description": "true (default) append delta; false replace entire pack",
                },
            },
            "required": ["context"],
        },
    },
    {
        "name": "btw_preview_instructions",
        "description": "Preview assembled system+context instructions and explain injection.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "profile": {"type": "string"},
                "context": {"type": "string"},
            },
        },
    },
    {
        "name": "btw_start",
        "description": (
            "Start /btw-vc Live voice for the active session. "
            "If context is set, it REPLACES the session pack (boot brief); omit to keep pack."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "profile": {"type": "string"},
                "context": {
                    "type": "string",
                    "description": "Optional. When provided, replaces session pack before boot inject.",
                },
                "use_mic": {"type": "boolean"},
                "muted": {"type": "boolean"},
            },
        },
    },
    {
        "name": "btw_stop",
        "description": "Stop Live voice runtime.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "btw_mute",
        "description": "Mute microphone (live or next start).",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "btw_unmute",
        "description": "Unmute microphone.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "btw_reinject",
        "description": "Re-send session brief: uplink TTS + best-effort plain DC if open.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "btw_import_cookies",
        "description": "Swap chatgpt.com Cookie header (new account). Clears token cache. Stop Live first.",
        "inputSchema": {
            "type": "object",
            "properties": {"cookie_header": {"type": "string"}},
            "required": ["cookie_header"],
        },
    },
    {
        "name": "btw_clear_cookies",
        "description": "Remove stored ChatGPT cookies and token cache (local logout).",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "btw_viz",
        "description": "Open the /btw-vc voice visualizer GUI (levels + mute/stop).",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "btw_viz_close",
        "description": "Close the voice visualizer window.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "btw_proxy",
        "description": (
            "HTTP proxy for ChatGPT mint/token/hydrate. "
            "action: status|on|off|auto|toggle. Optional url (socks5h://host:port). "
            "WebRTC media is never proxied here."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "status|on|off|auto|toggle (default status)",
                },
                "url": {
                    "type": "string",
                    "description": "Optional proxy URL when action=on (e.g. socks5h://127.0.0.1:10808)",
                },
            },
        },
    },
]


def handle_tool(name: str, args: dict) -> dict:
    try:
        if name == "btw_status":
            return _ok(service.status())
        if name == "btw_doctor":
            return _ok(service.doctor())
        if name == "btw_session_list":
            return _ok(service.session_list())
        if name == "btw_session_new":
            return _ok(
                service.session_new(
                    args["name"],
                    profile=args.get("profile") or "default",
                    context=args.get("context") or "",
                    voice=args.get("voice") or "",
                )
            )
        if name == "btw_list_voices":
            return _ok(service.list_tts_voices())
        if name == "btw_set_voice":
            return _ok(service.set_voice(args["voice"]))
        if name == "btw_session_use":
            return _ok(service.session_use(args["id_or_name"]))
        if name == "btw_session_delete":
            return _ok(service.session_delete(args["id_or_name"]))
        if name == "btw_session_bind":
            return _ok(service.session_bind(args["conversation_id"]))
        if name == "btw_session_fresh":
            return _ok(service.session_fresh())
        if name == "btw_session_sync":
            return _ok(service.session_sync())
        if name == "btw_set_profile":
            return _ok(service.set_profile(args["name"]))
        if name == "btw_push_context":
            append = args.get("append")
            if append is None:
                append = True
            return _ok(
                service.push_context(
                    args.get("context") or "",
                    append=bool(append),
                )
            )
        if name == "btw_preview_instructions":
            return _ok(
                service.preview_instructions(
                    profile=args.get("profile"),
                    context=args.get("context"),
                )
            )
        if name == "btw_start":
            # Preserve explicit null/omit vs empty string: only pass context if key present.
            start_kw: dict = {
                "profile": args.get("profile"),
                "use_mic": args.get("use_mic", True) is not False,
                "muted": bool(args.get("muted") or False),
            }
            if "context" in args and args.get("context") is not None:
                start_kw["context"] = args.get("context") or ""
            return _ok(service.start(**start_kw))
        if name == "btw_stop":
            return _ok(service.stop())
        if name == "btw_mute":
            return _ok(service.mute())
        if name == "btw_unmute":
            return _ok(service.unmute())
        if name == "btw_reinject":
            return _ok(service.reinject())
        if name == "btw_import_cookies":
            return _ok(service.import_cookies(args["cookie_header"]))
        if name == "btw_clear_cookies":
            return _ok(service.clear_cookies())
        if name == "btw_viz":
            return _ok(service.open_viz())
        if name == "btw_viz_close":
            return _ok(service.close_viz())
        if name == "btw_proxy":
            return _ok(
                service.proxy_control(
                    args.get("action") or "status",
                    url=args.get("url"),
                )
            )
        return _err(f"unknown tool {name}")
    except Exception as e:
        return _err(f"{type(e).__name__}: {e}")


def main() -> int:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        method = req.get("method")
        msg_id = req.get("id")
        params = req.get("params") or {}

        if method == "initialize":
            respond(
                msg_id,
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "btw", "version": __version__},
                },
            )
        elif method in ("notifications/initialized", "notifications/cancelled"):
            continue
        elif method == "tools/list":
            respond(msg_id, {"tools": TOOLS})
        elif method == "tools/call":
            tname = params.get("name")
            targs = params.get("arguments") or {}
            respond(msg_id, handle_tool(str(tname), targs if isinstance(targs, dict) else {}))
        elif method == "ping":
            respond(msg_id, {})
        else:
            if msg_id is None:
                continue
            respond(msg_id, error={"code": -32601, "message": f"Method not found: {method}"})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
