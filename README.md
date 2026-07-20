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
| Sessions | Named packs: profile + context + optional voice |
| Mute | Mic mute without ending the call |
| Voice | Speak voice id at mint (e.g. maple) |
| Context | Profile + short pack; spoken uplink brief (DC text best-effort) |
| `/btw-topup` | Mid-call curated fact snip (append + speak delta) |

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
| `/btw-topup` | mid-call context snip |
| `/btw-sessions` / `session-new` / `use` / `delete` | packs |
| `/btw-voice` | list/set speak voice |
| `/btw-cookies` | import or clear local cookies |
| `/btw-status` / `/btw-doctor` | health |

## CLI

```powershell
$env:PYTHONPATH="src"
python -m btw.runtime doctor
python -m btw.runtime run --profile default
python -m btw.runtime stop
```

## Limits

- Unofficial; endpoints and behavior can change without notice.
- Session context is spoken as a short audio brief; datachannel text inject is best-effort.
- Not full ChatGPT UI feature parity (widgets, etc.).
- Cookies = full account access — treat as secrets.

## Dev

```powershell
pip install -e ".[dev]"
pytest
```

## License

MIT (see `LICENSE` when present). Does not grant rights under OpenAI’s terms.
