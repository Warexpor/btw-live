---
name: btw-doctor
description: Diagnose /btw-vc install (cookies, accessToken, aiortc, runtime, proxy)
---

Call MCP `btw_doctor`. Report in ≤8 lines: cookies, access_token, aiortc/curl_cffi/sounddevice, pid_running, **proxy** (`enabled` + url or direct), last_error. If deps missing: `pip install -e .` from the btw plugin root.
