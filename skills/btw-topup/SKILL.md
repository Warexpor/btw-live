---
name: btw-topup
description: Mid-call curated context top-up for /btw-vc. Use for /btw-topup when Live is up and Grok has new short facts to inject.
---

# /btw-topup

Feed **what's new** into the active Live voice session as a **short spoken uplink inject** (SAPI TTS).

Not the whole Grok chat. Not a second full session brief.

## Flow

1. Curate a tight snip of **only new facts** since last inject (goal change, file, error, decision, test result). Target **≤280–400 chars spoken** (pack can be longer).
2. Call `btw_push_context` with that snip (default **append** pack; Live speaks **delta only**). Use `append=false` only to wipe and replace the whole pack mid-call.
3. Runtime: uplink TTS of the delta (product path). DC plain if channel still open is best-effort only.
4. Confirm in one line: topped up / delta_chars / live_push_queued / inject.

## Rules

- **Only on explicit user request.** Do not call `btw_push_context` unprompted. The user types `/btw-topup` or explicitly asks "top up" — otherwise keep quiet.
- **One top-up** per call. No multi-frame dump of session history.
- Brief but complete picture of the *delta* (agent already has boot brief + prior top-ups).
- Curated only. No secrets, cookies, tokens, giant logs.
- Do not restart Live for a top-up.
- You implement code; voice only advises.
