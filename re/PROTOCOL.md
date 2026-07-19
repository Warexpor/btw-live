# ChatGPT Live / Voice — protocol map (from HAR 2026-07-19)

Source: `chatgpt.com.har` (119 entries). Auth in capture: **cookies only** (zero `Authorization` headers).

## Call flow

```
browser (cookies + oai-* headers)
  │
  ├─ POST /backend-api/conversation/init     (optional context)
  ├─ POST /backend-api/f/conversation/prepare → conduit_token (text path; may be parallel)
  │
  └─ POST /realtime/wm?dcid=0   multipart
         fields: sdp (offer), session (JSON)
         ← 201 text/plain SDP answer (ice-lite + host candidates)
         then WebRTC media (UDP/TCP) — not in HAR
```

Telemetry labels: `voice_mode=wingman` on mint, also `bidi` / surface `modal_voice_picker`.  
Plan in this capture: `plan_type=free` (still got Live/wingman).

## Critical endpoint

### `POST https://chatgpt.com/realtime/wm?dcid=0`

**Status:** 201  
**Content-Type:** `multipart/form-data`

| Field | Type | Role |
|-------|------|------|
| `sdp` | text | WebRTC SDP offer (`m=audio` + `m=video` + datachannel) |
| `session` | JSON | Voice session config |

**Request headers (observed):**

- `Cookie` — full chatgpt.com session
- `oai-device-id` — UUID (matches `oai-did` cookie)
- `oai-session-id` — browser tab/session UUID
- `oai-language` — e.g. `en-US`
- `oai-client-version` — git hash build id
- `oai-client-build-number` — numeric
- `x-openai-target-path` / `x-openai-target-route` — `/realtime/wm`
- `Origin` / `Referer` — `https://chatgpt.com/`

**Authorization:** HAR may redact Bearer headers. Live mint returns **401 missing_authorization** without `Authorization: Bearer <accessToken>` from `GET /api/auth/session` (cookies alone mint session JSON, not `/realtime/wm`).

### `session` JSON shape

```json
{
  "backend_reasoning_effort": "instant",
  "language_code": "auto",
  "requested_default_model": "",
  "voice": "maple",
  "voice_session_id": "<uuid>",
  "voice_status_request_id": "<same uuid>",
  "timezone_offset_min": -180,
  "timezone": "Europe/Moscow",
  "voice_mode": "wingman",
  "model_slug": "",
  "model_slug_advanced": "",
  "client_tools": [],
  "history_and_training_disabled": false,
  "conversation_mode": { "kind": "primary_assistant" },
  "enable_message_streaming": true
}
```

### SDP answer (response body)

- `a=ice-lite`
- Audio mid `0`: opus (+ PCMU/PCMA), `sendrecv`, SSRC cname **`realtimeapi`**
- Video mid `1`: H264 variants, **`recvonly`** (camera optional; offer still negotiates video)
- Application mid `2`: **SCTP datachannel** (`a=sctp-port:5000`)
- ICE host candidates on Azure ranges, ports 3478 (UDP) / 443 (TCP passive)

## Related (text stack)

| Endpoint | Role |
|----------|------|
| `POST /backend-api/conversation/init` | defaults / limits |
| `POST /backend-api/f/conversation/prepare` | returns `conduit_token` JWT |
| `GET /backend-api/conversation/{id}` | thread dump |
| `POST /backend-api/sentinel/heartbeat` | sentinel keepalive |
| `POST /ces/*` | analytics only |

## Implementation implications

1. **Mint path is clear:** build WebRTC offer → multipart POST `/realtime/wm` → set remote SDP → ICE → audio + datachannel.
2. **Auth path is not bare-HTTP friendly:** same cookies get **CF 403** from Python; need browser/CDP TLS context or full CF clearance.
3. **Datachannel** likely carries events (transcripts, tool/state) — not reverse-engineered yet (media not in HAR). Capture next with `chrome://webrtc-internals` or CDP WebRTC stats / DC messages.
4. **Grok `/btw-vc` (standalone):** local aiortc + HTTP mint; system prompt via datachannel; optional headless token harvest only if CF blocks curl_cffi. See `src/btw/live_session.py`.
5. **Docs:** public framing in `docs/SAFE_DOCS.md` / root README.

## Local artifacts (gitignored)

- `re/captures/chatgpt.com.har`
- `re/captures/realtime_wm_*.txt|json|sdp`
- `re/captures/prepare_*.json`
- `re/captures/har_focus.json`
