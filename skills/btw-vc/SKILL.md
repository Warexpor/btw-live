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
4. On **start**, assembled instructions inject over datachannel (`session.update` + bootstrap user brief).
5. Mid-call: `btw_push_context` updates the pack and queues a live DC update.

## User phrases → tools

| User | Tools |
|------|--------|
| `/btw-vc` start | `btw_status` → optional `btw_push_context` → `btw_start` |
| stop | `btw_stop` |
| `/btw-mute` · `/btw-unmute` | `btw_mute` / `btw_unmute` |
| `/btw-sessions` | `btw_session_list` |
| `/btw-session-new` | `btw_session_new` |
| `/btw-session-use` | `btw_session_use` |
| `/btw-session-delete` | `btw_session_delete` |
| `/btw-voice` | `btw_list_voices` / `btw_set_voice` |
| push context | `btw_push_context` |
| reinject prompt | `btw_reinject` |
| doctor | `btw_doctor` |

## Start checklist

1. Cookies ok (`btw_status`).
2. Active session + profile correct.
3. Context snip if useful (≤4–6k).
4. `btw_start`.
5. One short confirm: live / muted / session name. No secrets.

## Rules

- Do not dump cookies, tokens, or full instructions.
- You implement code; voice only advises.
