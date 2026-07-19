# Changelog

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
