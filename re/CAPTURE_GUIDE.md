# ChatGPT Live — reverse-eng capture guide

Internal RE notes only. Do **not** commit authenticated HARs or cookies (`re/captures/` is gitignored). See `docs/SAFE_DOCS.md`.

Goal: map the **cookie → session mint → WebRTC** path for GPT-Live on web.

## 0. Cookies (CDP — required on modern Chrome)

Disk decrypt fails on Chrome App-Bound Encryption. Use CDP instead:

```powershell
cd C:\Users\amicu\chatgpt-live-bridge

# Option A — fresh profile (easiest; log in once):
.\scripts\start_chrome_cdp.ps1 -FreshProfile
# log into chatgpt.com in that window, then:
python scripts\extract_cookies_cdp.py
python scripts\probe_session.py

# Option B — main profile (quit ALL Chrome first):
.\scripts\start_chrome_cdp.ps1
python scripts\extract_cookies_cdp.py
python scripts\probe_session.py
```

Legacy disk extract (`extract_cookies.py`) only works if DPAPI works; expect it to fail.

## 1. HAR capture (required)

1. Open **Chrome** (same profile you extracted).
2. Go to https://chatgpt.com — confirm you are logged in.
3. F12 → **Network**
   - Preserve log: **ON**
   - Filter: `Fetch/XHR` first pass, then clear filter and also watch **WS**
4. Optional: right-click Network → **Clear browser cache** is NOT needed; just clear the network list.
5. Click the **Voice / Live** icon (composer). Allow mic if asked.
6. Speak 5–10 seconds, let it answer, then end the call.
7. In Network:
   - Search: `voice`, `realtime`, `rtc`, `live`, `webrtc`, `session`, `client_secret`, `ws`
   - Right-click any request → **Save all as HAR with content**
8. Save as:
   `C:\Users\amicu\chatgpt-live-bridge\re\captures\live-YYYYMMDD.har`

### What we care about

| Phase | Look for |
|-------|----------|
| Auth | `/api/auth/session`, accessToken in response |
| Mint | POST that returns room / client_secret / call_id / sdp / livekit |
| Media | `wss://` or ICE / SDP / `rtc` |
| Events | JSON messages on WS after connect |

## 2. Cookie-only check (already automated)

`probe_session.py` proves cookies still mint an `accessToken`.
Live mint almost always needs that Bearer token + browser-like headers, not raw cookies alone on every hop.

## 3. Security

- `re/captures/cookies.full.json`, `cookies.netscape`, `access_token.txt`, `*.har` are **secrets**.
- Do not commit. Do not paste full tokens into chat.

## 4. After HAR is on disk

Tell the agent: “HAR is at re/captures/live-….har”  
We will parse URLs, headers, and body shapes and implement the mint client.
