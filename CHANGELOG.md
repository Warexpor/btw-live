# Changelog

## 0.5.51 — 2026-07-20

### Fixed

- **Mid-output stutters (root cause from live logs):** speaker ring chronically empty under 40 ms cushion (`u` climbed every 5 s, `ring` stuck at 1–2 frames, `drop=0`). Restored real jitter buffer (~120 ms preroll, ~100 ms target, ~320 ms cap). **Post-gain packet join threshold was 0.08** — re-blended almost every WebRTC packet → warble; raised to 0.28 and only join on real jumps/lag-drops. Silence underruns no longer counted as speech underruns; clean zeros when quiet.

### Changed

- README limits + FEATURE_BACKLOG note the 0.5.51 playout buffer (docs catch-up with installed fix).

## 0.5.50 — 2026-07-20

### Added

- **`/btw-proxy`** skill + MCP `btw_proxy`: `status|on|off|auto|toggle` [url]. Preference in `proxy.json` (survives restarts). HTTP mint/token only; media still direct.

### Changed

- **Docs polish:** README slash table + proxy section + limits; SAFE_DOCS allow-list; FEATURE_BACKLOG mark proxy/inject/speaker shipped; doctor skill reports proxy; PROTOCOL notes HTTP proxy vs media.

## 0.5.49 — 2026-07-20

### Added

- **HTTP proxy:** ChatGPT token/mint/hydrate via `BTW_PROXY` / `HTTP(S)_PROXY` / Windows system proxy as **socks5h** (v2rayN/xray `127.0.0.1:10808`). Doctor + runtime log show proxy. `BTW_PROXY=0` = direct. **WebRTC media is still direct** (OS TUN if media must proxy).

### Changed

- **No artificial playout lag:** preroll/target ~40ms, high ~80ms, cap ~150ms, PortAudio `latency=low`. Audio boot settle 0; shorter DC defer timeouts.
- **Default: no unprompted context push.** Agent only calls `btw_push_context` on explicit `/btw-topup`. Skills `btw-vc`, `btw-topup`, `btw` updated to reflect this rule. Launch.cmd reverted — no `BTW_NO_AUDIO_INJECT` (audio works for manual topups).

## 0.5.48 — 2026-07-20

### Fixed

- **Mute UI flash:** optimistic mute held until meters agree (~900ms) so a stale poll cannot flip chrome/label for one frame; mute mix snaps on click.
- **Occasional playout lag:** adaptive ring trim — nibble toward ~120ms when above ~200ms; hard cap ~300ms (was 450ms sit-and-wait).

### Changed

- **Orb pulse stronger:** speak scale ~8–16%, more halo/core/ring breath while AI talks (still smooth, AI-only).

## 0.5.47 — 2026-07-20

### Fixed

- **Speaker cracks (root cause):** partial underruns hard-zeroed the shortfall → occasional clicks. Fade-hold like full underruns; post-gain packet joins; crossfade after underrun/lag-drop recovery. Preroll 100ms, ring max 450ms, PortAudio latency 0.08s.
- **`btw_start(context=...)` no longer appends onto a stale session pack.** Passing `context` **replaces** the pack before prepare/boot inject so the spoken brief matches this call. Omit `context` to keep the pack. Mid-call `/btw-topup` still appends by default.
- **MCP `btw_push_context`:** expose `append` (default true); `append=false` replaces the pack. Start tool blurb documents replace semantics. Skills (`btw-vc`, `btw-topup`) aligned.

### Added

- Speaker diagnostics: underruns / partial_underruns / ring_drops / sd_underflows in meters + runtime log.
- Start response fields `context_replaced`, `context_chars`. Push response field `replaced`.

## 0.5.46 — 2026-07-20

### Changed

- **Visualizer AI pulse more visible:** speak scale ~4–10% (was ~1–2.5%), stronger halo/core/ring breath and arc lift when she talks. Still AI-only, smooth (no mic drive, no tick thrash / jagged contour).

## 0.5.45 — 2026-07-20

### Fixed

- **Docs/MCP/skills lag:** product inject is uplink TTS (not plain-text DC). README, SAFE_DOCS, MCP tool blurbs, preview copy, hub + `/btw-vc` tables, status skill fields aligned. Session bind/fresh/sync listed in hub and README slash table.
- **`session_sync` error path:** peer to `session_bind` — soft-fail with `ok: false` + error instead of raising on fetch failure.

### Changed

- Feature backlog: mark viz/inject/bind shipped; suggested build order starts at Live HUD.

## 0.5.44 — 2026-07-20

### Changed

- **Visualizer transitions:** continuous mode mixes (live / muted / speak / inject) ease every frame — mute wash, nucleus sunset blend, wave colors, meter warn, mute button chrome. Optimistic mute on click/space. Softer level envelopes, longer speak latch, orb-label crossfade, CSS ease on chip/pill/segs/meta.

## 0.5.43 — 2026-07-20

### Changed

- **Visualizer orb calm pulse:** while AI speaks, no tick thrash / jagged histDn contour / sweep flare. Same idle dial; speech only adds a soft ~1–2.5% radius breath and slight core glow.

## 0.5.42 — 2026-07-20

### Fixed

- **Speaker stutter / scratch:** polish path was re-declicking and soft-limiting every 20ms block with a low jump threshold, which smeared real speech into grit and lag. Playback is clean again: hard gain limit only, rare digital-spike kill, no per-block crossfade; output `latency=low`; ring capped ~350ms so jitter backlog cannot pile into multi-second lag; shorter preroll (60ms). Meter disk writes reduced to ~10Hz.

## 0.5.41 — 2026-07-20

### Added

- **ChatGPT conversation bind + resume (C path):** named sessions store `conversation_id` (plus title / last `voice_session_id` / parent). MCP: `btw_session_bind`, `btw_session_fresh`, `btw_session_sync`. Skills for the same.
- **Hydrate:** on start, `GET /backend-api/conversation/{id}` → ASR turn snip → spoken uplink resume brief (prior voice turns + local pack).
- **Mint bind:** `/realtime/wm` session JSON includes `conversation_id` when bound (defensive `conversation_mode` fields). On 4xx, retry unbound mint; hydrate still runs. `BTW_NO_CONVERSATION_BIND=1` skips mint fields only.
- **Discover:** after stop, best-effort scan recent conversations for this leg’s `voice_session_id` and auto-bind if found.
- **`conversation.py`:** decode dump, extract voice turns, format resume snip; unit fixture + tests.

### Changed

- Status / session list show `resume`, `conversation_short`, title when bound.

## 0.5.40 — 2026-07-20

### Changed

- **Visualizer panel restored** to pre-overhaul deck: top bar, side meters/wave/meta cards, focus mode (not the full-stage singularity dock).
- **Orb pulse = AI only:** gated on downlink with noise threshold (`AI_THRESH` ~0.12); mic uplink no longer drives the ring. **Mute is my mic only** — ring keeps pulsing when she speaks; mute shows on you-meter + nucleus/label, not as a frozen orange dial.

## 0.5.39 — 2026-07-20

### Changed

- **Boot/top-up inject length:** uplink TTS queue **60s**; spoken boot cap **3200** chars, top-up **1200** (DC plain caps matched). Enough for a ~1 minute dense brief.
- **Visualizer:** true **circle** orb again (removed elliptical y-squash). **Stars are static** (fixed xy + twinkle only); only thin arc sweeps spin. Concentric circular rings + energy contour.

## 0.5.38 — 2026-07-20

### Fixed

- **Audio cracks (downlink + uplink):** do not hard-zero underruns or pass decode spikes. Speaker path: longer preroll (120ms), hold-decay on underrun, `_declick_join` at block edges, `_soften_intra_clicks` for single-sample glitches. Same join/soft on uplink (inject↔mic). Cannot invent missing OpenAI packets — only smooths our edges.
- **Boot inject too small:** product path was uplink TTS clipped to **420 chars** of context → ASR bubbles like “Session brief.” / “Cannot edit files.” Spoken brief now carries the real session pack (cap **1600**), speech-normalized; top-up **700**; inject queue **24s** so SAPI can finish.

### Changed

- **Visualizer redesign (xAI-ish):** simpler full-stage singularity (void + white outline + energy accretion ring + dust), thin dock meters, monochrome white pills. More dynamic energy response; less chrome.

## 0.5.37 — 2026-07-20

### Fixed

- **Live mic streaming / barge-in:** uplink no longer waits for a full utterance then dumps it. Root cause was double frame pacing (mic + inject wrapper) plus ring backlog catch-up — speech arrived late as a blob, so Wingman could not interrupt mid-talk like real ChatGPT Live. Now: single 20ms pacer on the outer track, mic `paced=False`, live-edge drop (~60ms), stall resync instead of dump, drain mic ring during TTS inject, `latency=low`.

## 0.5.36 — 2026-07-20

### Fixed

- **Context inject actually reaches Wingman:** plain DC UTF-8 is best-effort only (channel closes in ~100ms; agent ignores it). Product path is short **SAPI TTS on the mic uplink** after PC connects (boot) and on `/btw-topup` (delta). Disable with `BTW_NO_AUDIO_INJECT=1`.
- **Viz transitions** (idle / muted / talking): soft mode mixes every frame, slower level envelopes, longer speak hysteresis, softer segment fills and chip/label CSS easing — less snap.

## 0.5.35 — 2026-07-20

### Fixed

- **Crash on VC start** after 0.5.32: negotiated empty-label DC `id=0` makes `/realtime/wm` close the whole PeerConnection under aiortc (0 speaker frames). Primary DC is back to named `oai-events` (multi-minute sessions proven). Browser-style negotiated DC only if `BTW_DC_NEGOTIATED=1`.
- **Boot inject window**: server closes `oai-events` within ~100ms with no inbound; deferred wait missed the send. Default is one plain `channel.send` **immediately on DC open** (still exactly one message). Defer only if `BTW_DC_DEFER_BOOT=1`.

## 0.5.34 — 2026-07-20

### Fixed

- **Top-up** matches boot: exactly one plain-text DC message (`plain_topup_message` / WHAT'S NEW) with the session delta only — not a full re-brief, not multi-frame.
- Brief caps: boot ≤1800 chars, top-up ≤900 chars (normalize + smart clip) so injects stay small but still give a usable picture.

## 0.5.33 — 2026-07-20

### Fixed

- Boot inject is **exactly one** plain-text structured `channel.send` after VC init (`plain_boot_message`). No multi-entry list, no second send on retry after a successful first send, no double-arm.

## 0.5.32 — 2026-07-20

### Fixed

- Live **context inject DC parity**: open negotiated datachannel `id=0` with empty label (browser Wingman), not named `oai-events`.
- **Boot plain-text inject deferred** until first inbound DC message or ~0.75s timeout (plus one retry) so send does not race/close the channel on open.
- Mid-call top-up still one plain-text entry on the same open DC.

## 0.5.31 — 2026-07-20

### Fixed

- Viz one-frame **IDLE flash** (chip idle, meta `—`, waiting): sticky last-good meters on empty/failed polls; ignore transient non-live reads while live; `read_meters` retries on Windows file races; canvas bitmap resize threshold raised so DPI/scrollbar noise doesn’t clear the orb for a black frame.
- Clean Live end no longer leaves ghost `runtime.pid` / undrained control queue; stopped meters clear mute sticky.
- Docs/skills/preview path aligned to **plain-text DC** inject (not TTS-primary); plugin manifest version matches package; `install.ps1` force-syncs install tree when grok says already installed.

## 0.5.30 — 2026-07-20

### Fixed

- **Voice meters** now track real mic/speaker energy: RMS+peak frame level with attack/release envelope (was single-sample peak → mostly 0 with rare 1.0 spikes). Downlink meters post-gain/limit (what you hear). s16 uplink decode no longer lost dtype before scale.
- **Viz flash / state thrash**: removed speaking-mode chrome hide (chip/meta/hint opacity); stable orb labels; canvas no longer writes CSS size (absolute fill + bitmap only); smoother UI attack/release and longer seg transitions.

## 0.5.29 — 2026-07-20

### Changed

- Boot context inject is **always a single plain-text DC message** (session compact). Top-ups remain separate messages.

## 0.5.28 — 2026-07-20

### Changed

- **Context inject is plain text on the datachannel**, not TTS. On DC open: session brief + context blocks as raw UTF-8 entries. Mid-call top-ups are plain-text entries too.
- Audio TTS bootstrap/top-up is opt-in only (`BTW_AUDIO_BOOT=1` / `BTW_AUDIO_TOPUP=1`).
- Legacy Realtime JSON (`session.update` / `response.create`) opt-in only (`BTW_DC_REALTIME=1`) — that path was closing Wingman.

## 0.5.27 — 2026-07-20

### Fixed

- Live dying ~seconds after connect: default **no DC boot inject**. Realtime-style `session.update` / `response.create` on the Wingman datachannel closed DC + PC; product path is spoken bootstrap only (`BTW_DC_BOOT=1` to force old behavior).
- Viz surface flash: no layout reflow on `speaking` (removed gap change); speaking hysteresis; canvas resize ignores 1–2px jitter; DOM/seg updates only when values change; continuous rAF paint separate from meter poll.

## 0.5.26 — 2026-07-20

### Fixed

- Control IPC stop spam: clear `control.jsonl` on Live start and after runtime kill; first `stop` in a drain batch ends the loop so ESC key-repeat / orphan queues no longer log multi-stop and mute the dying session.

## 0.5.25 — 2026-07-20

### Changed

- App icon: rebuilt ring-dial asset set; set via `webview.start(icon=...)` (correct pywebview 6 API) so Windows shows the real icon instead of default Python.

## 0.5.24 — 2026-07-20

### Fixed

- Live surface was silently falling back to **tkinter** because pywebview rejected `icon=` on `create_window`. WebView path restored; errors go to `viz.log`; no silent tk unless `BTW_VIZ_ALLOW_TK=1`.

## 0.5.23 — 2026-07-20

### Added

- App icon: code-drawn ring-dial (`assets/icon.png` / `icon.ico`), wired into the live surface window.

## 0.5.22 — 2026-07-20

### Added

- **Focus / Deck** view toggle: full chrome vs visualizer-only (button, hover **Deck** exit, `F` key; remembers in localStorage).

### Changed

- Restored rich **idle** dial; speech only gently lengthens ticks / core (no curve/dot storm).

## 0.5.21 — 2026-07-20

### Changed

- Viz speech mode desaturated: dropped spark dots + wild polar squiggles; speech only lengthens ticks / softens core glow (idle dial look preserved).

## 0.5.20 — 2026-07-20

### Changed

- Viz reactor restored to **full ring energy** (layered rings, dual tick fields, dual polar waves, triple arcs, sparks) while keeping the clean starfield (no petal dust).
- Idle dial still breathes/spins lightly so it doesn’t look dead.

## 0.5.19 — 2026-07-20

### Fixed

- Viz: removed oversized solid dust ellipses (looked like gray petals over the reactor).
- Idle instrument cleaner: concentric guides + outer ticks only; polar waves only when signal present.
- Softer starfield/nebula washes; no double CSS blob layer fighting the canvas.

## 0.5.18 — 2026-07-20

### Changed

- Viz pane: **cosmic void** backdrop — parallax starfield, faint dusk/breeze nebulae, dust, vignette; reactor sits in full-pane canvas.
- Still monochrome-first (xAI accents only as whisper washes).

## 0.5.17 — 2026-07-20

### Changed

- Live surface **horizontal desktop layout** (~1080×420) for second-monitor parking.
- Removed film-grain noise layer; cleaner void canvas.
- **Ring-reactor** visualizer: radial tick spectrum, dual polar waveforms, orbiting arcs, spark satellites.
- While she speaks: chrome text fades (label / detail meta / hint) so the viz dominates.
- Slim top bar + compact meta strip (less label clutter).

## 0.5.16 — 2026-07-20

### Changed

- Live surface is now a **WebView2 / pywebview** app (HTML/CSS/JS): modern orb, spectrum, TRACE, telemetry; Python bridge for meters + mute/stop.
- `python -m btw.viz --demo` animates the shell without Live.
- tkinter UI kept as fallback (`BTW_VIZ_TK=1` or if pywebview missing).

## 0.5.15 — 2026-07-20

### Changed

- Visualizer redesigned as **second-monitor live surface** in xAI dark language: void canvas, hairline cards, pill controls, hero orb with ring pulse, segmented spectrum meters, dual waveform trace, full telemetry grid, keyboard shortcuts (SPACE mute, ESC end). Stays open after call ends for parking on a side display.

## 0.5.14 — 2026-07-20

### Added

- **Voice visualizer GUI** (`btw.viz` / `/btw-viz`): dual level bars, talking orb, session/voice chips, mute·unmute·stop.
- High-rate `meters.json` (~20 Hz) with `uplink_peak`, `downlink_peak`, `injecting`.
- Speaker downlink peak for “is she talking” UI.
- Auto-open visualizer on Live start; `BTW_NO_VIZ=1` or `--no-viz` to skip.
- MCP `btw_viz` / `btw_viz_close`; CLI `python -m btw.runtime viz`.

## 0.5.13 — 2026-07-20

### Added

- `docs/FEATURE_BACKLOG.md` — concrete product todo list (voice visualizer GUI, PTT, scene packs, auto-topup, etc.).
- README pointer under Roadmap.

## 0.5.12 — 2026-07-20

### Fixed

- `/btw-stop` kill path clears `live_status.json` (no ghost `status: live` after force kill).
- `btw_status` marks leftover live status as stopped/`stale` when runtime pid is dead.
- Plugin manifest version was stuck at 0.5.6; aligned to package version.

### Changed

- README + hub skill list `/btw-topup`; context line matches audio brief delivery.

## 0.5.11 — 2026-07-20

### Fixed

- Mic uplink after bootstrap: resync mic clock when inject ends; robust int16→float conversion; cap TTS inject at 8s; shorter spoken brief.
- Live status reports `uplink_peak` / `mic_frames` for “can she hear me” checks.

## 0.5.10 — 2026-07-20

### Fixed

- Background Live spawn hung (~5MB, no log) when started from MCP: inherit stdin blocked the child. Spawn with `stdin=DEVNULL`.

## 0.5.9 — 2026-07-20

### Fixed

- Pin MCP + Live to plugin `.venv` python (`BTW_PYTHON` / `python_exe()`). Bare PATH `python` was Hermes venv and hung/spawned the wrong env.
- `mcp/launch.cmd` refuses to start without `.venv`; `install.ps1` creates it and installs deps (uv preferred).

## 0.5.8 — 2026-07-20

### Added

- Audio context delivery: SAPI TTS → `InjectableUplinkTrack` bootstrap on start and mid-call top-up.
- `/btw-topup` skill — curated snip only; appends session pack; live audio inject primary path.
- `push_context` append mode (default) so top-ups do not wipe prior facts.

### Fixed

- Windows `btw_start` spawn hang: drop `DETACHED_PROCESS`; use `CREATE_NO_WINDOW` + `-u` + line-buffered log.
- Runtime passes `context.txt` into `LiveSession` so bootstrap speech has the pack.

### Changed

- DC `session.update` / reinject remains best-effort; product path is spoken uplink.

## 0.5.5 — 2026-07-20

### Fixed

- MCP server failed to start: plugin `.mcp.json` used relative `mcp/launch.cmd` and Grok did not set plugin cwd (`The system cannot find the path specified`).
- `install.ps1` now pins absolute `[mcp_servers.btw]` via `grok mcp add` (same pattern as wrath).

## 0.5.6 — 2026-07-20

### Fixed / polish

- LICENSE (MIT), gitignore egg-info/secrets, install version string, doctor skill copy.
- service unused imports / prepare payload write-through; session list `voice_effective`.
- Removed unused `live_boot.js` (browser Live path abandoned).
- RE docs pointer to SAFE_DOCS.

## 0.5.5 — 2026-07-20

### Added

- `docs/SAFE_DOCS.md` — public/docs framing (unofficial, ToS risk, no secrets).
- README rewritten to that standard.

## 0.5.4 — 2026-07-20

### Added

- `/btw-cookies` — import or clear ChatGPT Cookie header (account swap).
- `btw_clear_cookies`; import clears token cache and refuses while Live is running.

## 0.5.3 — 2026-07-20

### Added

- Speak **voice** management: `voices.py` allowlist, session override, mint `session.voice`.
- MCP `btw_list_voices` / `btw_set_voice`; slash `/btw-voice`.
- Voice applies at start (mint); change needs stop + start if live.

## 0.5.2 — 2026-07-20

### Added

- Slash skills: `/btw-sessions`, `/btw-session-new`, `/btw-session-use`, `/btw-session-delete`.

## 0.5.1 — 2026-07-20

### Added

- Slash skills `/btw-mute` and `/btw-unmute`.

## 0.5.0 — 2026-07-20

### Added

- Named **sessions** (profile + context pack): list/new/use/delete.
- **Mic mute/unmute** live via control IPC (`btw_mute` / `btw_unmute`).
- Prompt injection: `session.update` + system item + bootstrap user brief; mid-call `push_context` / `reinject`.
- Live status file + control queue for running process.
- MCP tools for sessions, mute, reinject.

### Changed

- `/btw-vc` skill documents btw-style context flow.

## 0.4.2 — 2026-07-20

### Added

- Slash skill **`/btw-vc`** for Live voice (separate from hub `/btw`).

### Changed

- `/btw` hub points to `/btw-vc` for talk sessions.

## 0.4.1 — 2026-07-20

### Fixed

- Audio pitch/pops: `AudioResampler` → 48 kHz mono; ring buffer; stereo output devices; mic rate adapt + pacing.

## 0.4.0 — 2026-07-20

### Changed

- **Standalone Live path** — Live session is not a ChatGPT browser tab.
- Auth: cookies → `accessToken` (`curl_cffi` first; **token-only** headless Playwright if CF 403s).
- Token cache: `~/.grok/btw/access_token_cache.json`.
- Mint `POST /realtime/wm` with **aiortc** SDP + local mic/speaker (`sounddevice`).
- `btw_start` / CLI spawn standalone process.

### Verified (`mint-smoke`)

- mint **201**, ICE **completed**, PC **connected**, audio+video tracks, DC open→send instructions.

### Removed (as primary path)

- Playwright as the Live UI / full chat page shell.

### Added

- `http_client.py`, `live_session.py`, `audio_io.py`, `mint-smoke`

## 0.3.x — 2026-07-20

Playwright tab prototype (mint 201 proven; headed mic/CF flaky).

## 0.2.0 — 2026-07-20

Profiles, MCP prepare/status, skills.

## 0.1.x — 2026-07-20

HAR reverse-eng, cookie import, protocol map.
