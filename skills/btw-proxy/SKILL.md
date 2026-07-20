---
name: btw-proxy
description: Toggle / show ChatGPT HTTP proxy for /btw-vc (mint/token/hydrate). Use for /btw-proxy on|off|auto|toggle.
argument-hint: "[status|on|off|auto|toggle] [url]"
---

# /btw-proxy

Routes **HTTP only** (token, mint, conversation hydrate) via SOCKS/HTTP proxy. **WebRTC audio is never proxied** (needs OS TUN).

## Behavior

Call MCP `btw_proxy`:

| Args | Call |
|------|------|
| none / `status` | `btw_proxy(action="status")` |
| `off` / `direct` | `btw_proxy(action="off")` |
| `on` | `btw_proxy(action="on")` — uses last url or system proxy |
| `on socks5h://127.0.0.1:10808` | `btw_proxy(action="on", url="…")` |
| `auto` | `btw_proxy(action="auto")` — env + Windows system proxy |
| `toggle` | `btw_proxy(action="toggle")` |

## Confirm (≤3 lines)

- `enabled` + `url` (or direct)
- `mode` (on/off/auto)
- note: media stays direct; Live already running keeps same HTTP clients until next mint/token fetch (restart Live if mid-call auth fails after toggle)
