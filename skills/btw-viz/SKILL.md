---
name: btw-viz
description: Open the /btw-vc voice visualizer GUI (mic/her levels, mute, stop). Use for /btw-viz.
---

# /btw-viz

Opens the **second-monitor live surface** for `/btw-vc` (WebView2 / pywebview):

- Modern HTML UI — hero orb, spectrum, TRACE, telemetry
- Pills: Mute / End call · SPACE mute · ESC end
- Demo shell (no Live): `python -m btw.viz --demo`

## Steps

1. Call MCP **`btw_viz`** (or `python -m btw.runtime viz`).
2. Drag to second monitor.
3. `/btw-vc` auto-opens unless `BTW_NO_VIZ=1`.
4. Close: window X or `btw_viz_close`.
5. Fallback: `BTW_VIZ_TK=1` for old tk shell.
