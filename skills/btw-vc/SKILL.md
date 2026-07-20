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
4. On **start**, the **session pack** is spoken onto the mic uplink (SAPI TTS) after PC connects. DC plain is best-effort. Disable with `BTW_NO_AUDIO_INJECT=1`.
5. **`btw_start(context=...)` REPLACES the pack** before boot. Omit `context` to keep the existing pack. Never rely on append for a new call brief.
6. Mid-call: `/btw-topup` → `btw_push_context` **appends** pack + spoken delta (`append=false` to wipe/replace mid-call).

## User phrases → tools

| User | Tools |
|------|--------|
| `/btw-vc` start | `btw_status` → `btw_start` with **this call's** context snip (replaces pack). Do not pre-`push_context` append then start. |
| `/btw-viz` | `btw_viz` — levels GUI |
| stop | `btw_stop` |
| `/btw-mute` · `/btw-unmute` | `btw_mute` / `btw_unmute` |
| `/btw-sessions` | `btw_session_list` |
| `/btw-session-new` | `btw_session_new` |
| `/btw-session-use` | `btw_session_use` |
| `/btw-session-delete` | `btw_session_delete` |
| `/btw-session-bind` | `btw_session_bind` (uuid or chatgpt.com URL) |
| `/btw-session-fresh` | `btw_session_fresh` |
| `/btw-session-sync` | `btw_session_sync` |
| `/btw-voice` | `btw_list_voices` / `btw_set_voice` |
| `/btw-topup` / push context | `btw_push_context` (append pack + uplink TTS delta; `append=false` replace) |
| reinject prompt | `btw_reinject` |
| doctor | `btw_doctor` |

## Start checklist

1. Cookies ok (`btw_status`).
2. Active session + profile correct.
3. Curate **this call's** context snip only (≤4–6k). Advisory Grok facts — not mic/SAPI/viz ops meta, not prior version dump.
4. `btw_start(context=snip)` so pack is replaced and boot inject matches the snip. Omit context only when reusing the pack on purpose.
5. **Resume (optional):** if active session has `conversation_id` / `resume: true`, start hydrates prior ChatGPT voice turns and mints with that id. Bind with `/btw-session-bind`; clear with `/btw-session-fresh`; refresh metadata with `/btw-session-sync`.
6. One short confirm: live / muted / session name / resume? / context_replaced? / viz. No secrets.

## Rules

- Do not dump cookies, tokens, or full instructions.
- You implement code; voice only advises.
