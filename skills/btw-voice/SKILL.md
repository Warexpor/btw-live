---
name: btw-voice
description: List or set /btw-vc speak voice. Use for /btw-voice and when user wants maple/sol/sage etc.
argument-hint: "[list|voice-name]"
---

# /btw-voice

Live agent **speak** voice (mint `session.voice`). Not mic mute.

## Behavior

- No args or `list` → call `btw_list_voices`. Show voices + current effective.
- A voice name (e.g. `maple`, `sol`, `sage`) → call `btw_set_voice` with that name.
- Confirm: session, voice_effective. Note: **restart Live** (`/btw-stop` then `/btw-vc`) if already live — voice is fixed at mint.

Do not dump full cookie/session secrets.
