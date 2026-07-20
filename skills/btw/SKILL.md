---
name: btw
description: btw hub for Grok Build. Voice Live is /btw-vc — use that skill for talk sessions.
---

# /btw — hub

**Live voice** = **`/btw-vc`** (skill `btw-vc`). Do not start voice on bare `/btw`.

| Command | Skill |
|---------|--------|
| `/btw-vc` | btw-vc — start/stop Live voice |
| `/btw-stop` | btw-stop — end Live |
| `/btw-mute` | btw-mute — mic mute only |
| `/btw-unmute` | btw-unmute — mic on |
| `/btw-topup` | mid-call curated context snip |
| `/btw-sessions` | list packs |
| `/btw-session-new` | create pack |
| `/btw-session-use` | switch pack |
| `/btw-session-delete` | delete pack |
| `/btw-session-bind` | bind ChatGPT conversation_id (resume) |
| `/btw-session-fresh` | clear conversation bind |
| `/btw-session-sync` | refresh bound conversation metadata |
| `/btw-voice` | list/set speak voice |
| `/btw-cookies` | swap/clear ChatGPT cookies |
| `/btw-status` | btw-status |
| `/btw-doctor` | btw-doctor |
| `/btw-proxy` | HTTP proxy on/off/auto (mint only; not media) |
| `/btw-viz` | voice visualizer GUI |

If user only said `/btw`, point them to `/btw-vc` in ≤5 lines.

**Default: no unprompted context push.** Agent only calls `btw_push_context` on explicit `/btw-topup`.
