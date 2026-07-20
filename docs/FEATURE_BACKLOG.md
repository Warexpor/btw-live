# Feature backlog

Cool product work on top of the working Live base. **Not** polish/hygiene.
Last updated: 2026-07-20.

Priority is a suggestion only — reorder when building.

---

## Active direction

### [x] Voice visualizer + second-monitor surface (0.5.14–0.5.16, calm/transitions 0.5.43–0.5.44)
- [x] WebView2 (pywebview) modern HTML surface; tk fallback
- [x] Tall always-on-top window for side display
- [x] xAI void canvas: hairline cards, pill CTAs, mono telemetry
- [x] Hero orb + segmented YOU/HER spectrum + dual TRACE waveform
- [x] Session / voice / mic / pc·ice telemetry grid
- [x] Mute / End call + SPACE / ESC; inject + mute states
- [x] Launch with `/btw-vc` and/or `/btw-viz`; `--demo` shell
- [x] Separate process + `meters.json` (~10–20 Hz)
- [x] AI-only orb pulse; calm speech breath; continuous mode mixes

### [x] ChatGPT conversation bind + resume (0.5.41)
- [x] Named sessions store `conversation_id` / title / parent
- [x] `/btw-session-bind` · `fresh` · `sync` + MCP tools
- [x] Hydrate resume snip → uplink TTS brief; mint bind fields with unbound retry

### [x] Product inject path = uplink TTS (0.5.36+)
- [x] Boot / top-up spoken on mic uplink (DC plain best-effort only)

---

## Presence & control

### [ ] Live HUD line
One always-available status line: voice, mute, session name, uplink peak, “she last spoke ~Ns ago”. No hunting `/btw-status`.

### [ ] Push-to-talk mode
Mic muted by default; open only while held/toggled for intentional speech. Coding-noise friendly.

### [ ] Soft end
Before hangup, inject a one-line “wrap up in one sentence” so the call does not die mid-thought.

---

## Context magic

### [ ] Auto-topup from Grok
After a coding beat, offer 1–2 spoken facts (“we just fixed spawn hang”) without rewriting the full pack. Curated, not a dump.

### [ ] Scene packs
One-shot moods as named packs (profile + short context + optional voice), e.g.:
- debug this crash
- rubber-duck design
- explain like I’m tired
- pair-program this file  
One slash to switch scene.

### [ ] “What I told her”
Surface last spoken bootstrap brief + top-ups so the side-channel memory is inspectable.

---

## Multi-session

### [ ] Dual personality slots
Hot-flip default ↔ debugger (or packs) mid-call with a clean re-brief when the stack allows; avoid full stop/start if possible.

### [ ] Sticky last session
`/btw-vc` reopens the pack used last time, not always `default`.

---

## Fun / power-user

### [ ] Voice + rate presets
Named presets (e.g. “maple calm”, “maple fast stand-up”), not raw voice ids only.

### [ ] Clip a recap
Optional local transcript or “last ~30s of her speech → note in session pack” for later Grok context.

### [ ] Hotkey layer
Global mute / topup / stop (tray or OS hotkeys) while staying in the IDE. Outside Grok slash if needed.

---

## Explicit non-goals (side channel stays the product)

- Second coding agent that writes code for you
- Full ChatGPT UI / widget parity
- Scope creep: theming engines, full spectrograms, Electron shell (unless product forces it)

---

## Suggested build order (if nothing else pulls)

1. Live HUD line (cheap presence)
2. Push-to-talk
3. Scene packs + sticky last session
4. “What I told her” + auto-topup
5. Soft end / presets / recap / hotkeys as appetite allows
