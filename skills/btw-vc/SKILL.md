---
name: btw-vc
description: ChatGPT Live voice side-session (/btw-vc). Sessions, context packs, mute, start/stop. Use for /btw-vc and voice talk with Grok context.
---

# /btw-vc

Separate Live voice channel. Not the coding agent.

## How context works (like /btw)

1. **Profile** = system rules (`sessions/*.toml`: default / debugger / architect).
2. **Session** = named pack: profile + context text.
3. **Context** = short Grok facts (goal, files, errors). Stored on the active session.
4. On **start**, context is spoken onto the mic uplink (short SAPI TTS) after PC connects — Wingman only reliably hears audio. DC plain is best-effort. Disable with `BTW_NO_AUDIO_INJECT=1`.
5. Mid-call: `/btw-topup` → `btw_push_context` appends pack + spoken delta on uplink (same path).

## User phrases → tools

| User | Tools |
|------|--------|
| `/btw-vc` start | `btw_status` → optional `btw_push_context` → `btw_start` (opens visualizer) |
| `/btw-viz` | `btw_viz` — levels GUI |
| stop | `btw_stop` |
| `/btw-mute` · `/btw-unmute` | `btw_mute` / `btw_unmute` |
| `/btw-sessions` | `btw_session_list` |
| `/btw-session-new` | `btw_session_new` |
| `/btw-session-use` | `btw_session_use` |
| `/btw-session-delete` | `btw_session_delete` |
| `/btw-voice` | `btw_list_voices` / `btw_set_voice` |
| `/btw-topup` / push context | `btw_push_context` (append pack + uplink TTS delta) |
| reinject prompt | `btw_reinject` |
| doctor | `btw_doctor` |

## Start checklist

1. Cookies ok (`btw_status`).
2. Active session + profile correct.
3. Context snip if useful (≤4–6k).
4. **Resume (optional):** if active session has `conversation_id` / `resume: true`, start hydrates prior ChatGPT voice turns and mints with that id. Bind with `/btw-session-bind`; clear with `/btw-session-fresh`; refresh metadata with `/btw-session-sync`.
5. `btw_start` (auto-opens visualizer unless `BTW_NO_VIZ`).
6. One short confirm: live / muted / session name / resume? / viz. No secrets.

## Rules

- Do not dump cookies, tokens, or full instructions.
- You implement code; voice only advises.
