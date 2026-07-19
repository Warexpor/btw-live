---
name: btw-session-new
description: Create a named /btw-vc voice session and make it active. Use for /btw-session-new.
argument-hint: name [profile] [context...]
---

Parse the user's args after the command:

1. **name** (required) — session name  
2. optional **profile** — `default` | `debugger` | `architect` (default: `default`)  
3. optional **context** — rest of the line as context snip  

Call `btw_session_new` with `{ "name", "profile", "context" }`.  
Confirm: created, now active, profile, context_chars. One short reply.
