---
name: btw-cookies
description: Import/swap chatgpt.com Cookie header for /btw-vc account. Use for /btw-cookies and account switch.
argument-hint: "[paste Cookie header | clear]"
---

# /btw-cookies

Swap the ChatGPT **web session** used by Live (not API keys).

## Behavior

1. Empty / `help` — how to export Cookie from chatgpt.com (DevTools → Network → Cookie header), or `clear`.
2. `clear` / `reset` → MCP `btw_clear_cookies`. Confirm removed file count. No secrets.
3. Else full Cookie string → MCP `btw_import_cookies` with `{ "cookie_header": "..." }`, then summarize auth ok/fail only (no values).

## Rules

- Never echo full cookies or access tokens back into chat.
- If import fails, say so in one line and ask for a fresh export from the browser.
