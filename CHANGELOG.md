# Changelog

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
