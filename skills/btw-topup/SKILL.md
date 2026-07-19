---
name: btw-topup
description: Mid-call curated context top-up for /btw-vc. Use for /btw-topup when Live is up and Grok has new short facts to inject.
---

# /btw-topup

Feed **short curated facts** into the active Live voice session. Not the whole Grok chat.

## Flow

1. Build a tight snip (goal, file, error, decision) — prefer ≤500–900 chars for speech.
2. Call `btw_push_context` with that snip (service **appends** by default).
3. If Live is running: runtime speaks the delta over the uplink (TTS) and best-effort DC.
4. Confirm in one line: topped up / chars / live_push_queued.

## Rules

- Curated only. No dumps, secrets, cookies, tokens.
- Do not restart Live for a top-up.
- You implement code; voice only advises.
