---
name: btw-session-bind
description: Bind active /btw-vc session to a ChatGPT conversation_id. Use for /btw-session-bind and continue-thread.
argument-hint: conversation-id-or-url
---

# /btw-session-bind

Bind the **active** named session to a real ChatGPT conversation so the next `/btw-vc` can resume that thread.

## Call

`btw_session_bind` with `{ "conversation_id": "<uuid or https://chatgpt.com/c/...>" }`.

## After

- Confirm session name, conversation short id, title (if fetched), turn_count.
- Next `/btw-vc` hydrates a spoken resume brief from `GET conversation/{id}` and mints with `conversation_id` when bind is allowed.
- `/btw-session-fresh` clears the bind. `/btw-session-sync` refreshes title/preview without starting Live.

No cookies/tokens in the reply.
