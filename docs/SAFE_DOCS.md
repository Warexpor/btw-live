# Documentation standard (public / future release)

Apply this whenever README, skill text, marketing, or install docs are written.

## Framing

- **Unofficial.** Not affiliated with OpenAI or xAI.
- **Not the supported product path.** Prefer OpenAI’s **official APIs** (e.g. Realtime) for production or redistribution.
- **Personal / research.** Session cookies and reverse-engineered web endpoints may **violate OpenAI Terms of Use**. Risk sits with the operator (account limits/bans). Do not claim “ToS-compliant” or “fully legal under OpenAI’s terms.”
- **No bypass marketing.** Do not pitch as free Plus/Pro, free Live, or “evade” OpenAI.

## Secrets

- Never commit cookies, HARs with auth, access tokens, or `.grok/btw` data.
- Docs may say *where* to put a Cookie header; never paste real values into the repo or examples.
- Capture dirs (`re/captures/`) stay gitignored.

## What docs may describe

- Architecture at a high level (auth → mint → WebRTC).
- Install, slash commands, sessions, mute, voice pick.
- Honest limits (DC injection best-effort, cookie expiry, not full ChatGPT UI parity).

## What docs should avoid

- Step-by-step “steal cookies from someone else.”
- Guarantees of continued endpoint stability or OpenAI permission.
- Shipping as an official OpenAI or ChatGPT integration.
