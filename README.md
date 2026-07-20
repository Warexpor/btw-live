# btw — Live voice side channel for Grok Build

**Unofficial. Not affiliated with OpenAI or xAI.**

Grok Build plugin: **`/btw-vc`** — local Live-style voice side session (mic/speakers + session packs). For supported production voice, use OpenAI’s **official APIs** (e.g. Realtime) under their terms and billing.

This project talks to **chatgpt.com** using a **browser session you already own** (Cookie header). That is **not** an official client path and **may violate OpenAI’s Terms of Use**. Use only with accounts you control, at your own risk. Do not publish cookies, tokens, or authenticated captures.

See [docs/SAFE_DOCS.md](docs/SAFE_DOCS.md) for how we write docs going forward.

---

## What it does

| Piece | Role |
|-------|------|
| `/btw-vc` | Start Live-style voice for the active session pack |
| Sessions | Named packs: profile + context + optional voice + optional ChatGPT bind |
| Mute | Mic mute without ending the call |
| Voice | Speak voice id at mint (e.g. maple) |
| Context | Profile + short pack; spoken on mic uplink (SAPI TTS) after connect. `btw_start(context=…)` **replaces** pack; omit keeps pack. |
| `/btw-topup` | Mid-call curated fact snip (append pack + uplink TTS delta; `append=false` replaces). **Only on explicit request** — no unprompted push. |
| Resume | `/btw-session-bind` → hydrate prior turns + mint with `conversation_id` |
| `/btw-proxy` | HTTP proxy for token/mint/hydrate (`on`/`off`/`auto`/`toggle`). **Not** WebRTC media. |
| `/btw-viz` | Second-monitor live surface (WebView UI, levels + mute/stop) |

Not a second coding agent. Side channel only.

## Install (Grok)

```powershell
cd <this-repo>
pip install -e .
.\install.ps1
```

`install.ps1` pins an **absolute** `[mcp_servers.btw]` path in `~/.grok/config.toml` (plugin `.mcp.json` relative `mcp/launch.cmd` fails when Grok does not set plugin cwd). Restart Grok after install so MCP reconnects.

Reload Grok plugins. Store session cookies **only** on your machine:

```
%USERPROFILE%\.grok\btw\cookie_header.txt
```

Or `/btw-cookies` (never commit that file).

## Commands (slash)

| Command | Effect |
|---------|--------|
| `/btw-vc` | start |
| `/btw-stop` | end call |
| `/btw-mute` / `/btw-unmute` | mic |
| `/btw-topup` | mid-call context snip (explicit only) |
| `/btw-viz` | voice visualizer GUI |
| `/btw-sessions` / `session-new` / `use` / `delete` | packs |
| `/btw-session-bind` / `fresh` / `sync` | ChatGPT conversation resume |
| `/btw-voice` | list/set speak voice |
| `/btw-proxy` | HTTP proxy status / on / off / auto / toggle |
| `/btw-cookies` | import or clear local cookies |
| `/btw-status` / `/btw-doctor` | health |

## CLI

```powershell
$env:PYTHONPATH="src"
python -m btw.runtime doctor
python -m btw.runtime run --profile default
python -m btw.runtime stop
```

## Proxy (HTTP only)

ChatGPT **token / mint / conversation** HTTP can go through a SOCKS or HTTP proxy:

| Control | How |
|---------|-----|
| Slash | `/btw-proxy` · `on` · `off` · `auto` · `toggle` · optional `url` |
| Persist | `~/.grok/btw/proxy.json` (`mode` + last `url`) |
| Env | `BTW_PROXY=socks5h://host:port` · `BTW_PROXY=0` = direct (env still honored when mode is not forced off via file) |
| Default (`auto`) | `HTTP(S)_PROXY` / `ALL_PROXY`, else Windows system proxy (WinINET) as `socks5h` |

**WebRTC media is never routed here.** For media via VPN/proxy use OS TUN (e.g. v2rayN TUN). Doctor/status expose `proxy.enabled` + `url`.

## Limits

- Unofficial; endpoints and behavior can change without notice.
- Product context inject is **uplink TTS** on start/top-up (Wingman hears audio). Disable with `BTW_NO_AUDIO_INJECT=1`. Plain DC is best-effort only.
- Agent must **not** call `btw_push_context` unless the user explicitly top-ups.
- Conversation resume bind is best-effort (hydrate proven; mint bind fields may fall back unbound on 4xx).
- HTTP proxy does **not** fix mid-speech audio; media is WebRTC direct unless OS TUN.
- Downlink uses a ~100–120 ms playout jitter buffer (cap ~320 ms). Too-thin buffers caused mid-speech underrun stutters; see CHANGELOG 0.5.51.
- Not full ChatGPT UI feature parity (widgets, etc.).
- Cookies = full account access — treat as secrets.

## Roadmap

Product ideas (PTT, scene packs, Live HUD, etc.): [docs/FEATURE_BACKLOG.md](docs/FEATURE_BACKLOG.md).

## Dev

```powershell
pip install -e ".[dev]"
pytest
```

## License

MIT (see `LICENSE` when present). Does not grant rights under OpenAI’s terms.
