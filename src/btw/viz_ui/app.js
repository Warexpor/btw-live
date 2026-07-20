/* btw live surface — horizontal desktop + ring-reactor viz */
(function () {
  const SEGS = 40;
  const HISTORY = 128;

  const state = {
    up: 0,
    dn: 0,
    histUp: new Array(HISTORY).fill(0),
    histDn: new Array(HISTORY).fill(0),
    muted: false,
    live: false,
    injecting: false,
    speaking: false,
    speakLatch: 0,
    focus: false,
    t0: performance.now(),
    bridge: "file",
    lastStatus: "",
    lastMuteLabel: "",
    lastHint: "",
    lastOrb: "",
    lastSegUp: "",
    lastSegDn: "",
    lastTele: {},
  };

  const el = {
    status: document.getElementById("statusChip"),
    orb: document.getElementById("orb"),
    orbLabel: document.getElementById("orbLabel"),
    upPct: document.getElementById("upPct"),
    dnPct: document.getElementById("dnPct"),
    upTrack: document.getElementById("upTrack"),
    dnTrack: document.getElementById("dnTrack"),
    wave: document.getElementById("wave"),
    btnMute: document.getElementById("btnMute"),
    btnStop: document.getElementById("btnStop"),
    btnView: document.getElementById("btnView"),
    btnViewExit: document.getElementById("btnViewExit"),
    hint: document.getElementById("hint"),
    tele: {
      session: document.querySelector('[data-k="session"]'),
      profile: document.querySelector('[data-k="profile"]'),
      voice: document.querySelector('[data-k="voice"]'),
      mic: document.querySelector('[data-k="mic"]'),
      channel: document.querySelector('[data-k="channel"]'),
      link: document.querySelector('[data-k="link"]'),
    },
  };

  function setFocusMode(on) {
    state.focus = !!on;
    document.body.classList.toggle("mode-focus", state.focus);
    if (el.btnView) {
      el.btnView.textContent = state.focus ? "Deck" : "Focus";
    }
    try {
      localStorage.setItem("btw_viz_focus", state.focus ? "1" : "0");
    } catch (_) {}
    // canvas must remeasure after layout change
    requestAnimationFrame(() => {
      paintOrb(state.dn, state.up, state.live, state.muted, false);
      paintWave();
    });
  }

  function toggleFocusMode() {
    setFocusMode(!state.focus);
  }

  try {
    if (localStorage.getItem("btw_viz_focus") === "1") {
      setFocusMode(true);
    }
  } catch (_) {}

  const orbCtx = el.orb.getContext("2d");
  const waveCtx = el.wave.getContext("2d");

  function buildTrack(track) {
    track.innerHTML = "";
    const nodes = [];
    for (let i = 0; i < SEGS; i++) {
      const d = document.createElement("div");
      d.className = "seg";
      track.appendChild(d);
      nodes.push(d);
    }
    return nodes;
  }

  const upSegs = buildTrack(el.upTrack);
  const dnSegs = buildTrack(el.dnTrack);

  function clamp01(x) {
    x = +x || 0;
    return x < 0 ? 0 : x > 1 ? 1 : x;
  }

  function level(peak) {
    return Math.pow(clamp01(Math.abs(+peak || 0) * 2.4), 0.72);
  }

  function paintSegs(nodes, v, mode, cacheKey) {
    const lit = Math.round(clamp01(v) * SEGS);
    const key = mode + ":" + lit;
    if (state[cacheKey] === key) return;
    state[cacheKey] = key;
    for (let i = 0; i < SEGS; i++) {
      const n = nodes[i];
      let cls = "seg";
      if (i < lit) {
        cls += " on";
        if (mode === "warn") {
          cls += i > SEGS * 0.7 ? " warn-peak" : " warn";
        } else if (i > SEGS * 0.85) {
          cls += " peak";
        } else if (i > SEGS * 0.5) {
          cls += " hot";
        }
      }
      if (n.className !== cls) n.className = cls;
    }
  }

  /* ── cosmic field + ring reactor ───────────────────── */
  // deterministic star catalog (unit coords)
  let stars = [];
  let fieldKey = "";

  function seeded(n) {
    let s = (n * 1103515245 + 12345) >>> 0;
    return function () {
      s = (s * 1664525 + 1013904223) >>> 0;
      return s / 0xffffffff;
    };
  }

  function ensureField(w, h) {
    const key = w + "x" + h;
    if (key === fieldKey && stars.length) return;
    fieldKey = key;
    const rnd = seeded((w * 73856093) ^ (h * 19349663) ^ 0x627477);
    stars = [];
    const nStars = Math.floor((w * h) / 4200) + 36;
    for (let i = 0; i < nStars; i++) {
      stars.push({
        x: rnd(),
        y: rnd(),
        r: 0.35 + rnd() * 1.1,
        a: 0.12 + rnd() * 0.4,
        tw: rnd() * Math.PI * 2,
        sp: 0.35 + rnd() * 1.1,
        layer: rnd() < 0.12 ? 2 : rnd() < 0.45 ? 1 : 0,
      });
    }
  }

  function sizeOrb() {
    const dpr = window.devicePixelRatio || 1;
    const pane = el.orb.parentElement;
    const rect = pane.getBoundingClientRect();
    const cssW = Math.max(200, Math.floor(rect.width));
    const cssH = Math.max(200, Math.floor(rect.height));
    const w = Math.floor(cssW * dpr);
    const h = Math.floor(cssH * dpr);
    // Ignore 1–2px jitter (reflow noise) so the canvas is not reset every frame
    const dw = Math.abs(el.orb.width - w);
    const dh = Math.abs(el.orb.height - h);
    if (dw > 2 || dh > 2 || !el.orb.width) {
      el.orb.width = w;
      el.orb.height = h;
      el.orb.style.width = cssW + "px";
      el.orb.style.height = cssH + "px";
      fieldKey = "";
    }
    return { w: el.orb.width, h: el.orb.height, dpr };
  }

  function paintCosmos(c, w, h, t, live, energy, muted) {
    ensureField(w, h);

    // deep void — pure, no petal blobs
    const voidG = c.createRadialGradient(
      w * 0.5,
      h * 0.45,
      0,
      w * 0.5,
      h * 0.5,
      Math.max(w, h) * 0.8
    );
    voidG.addColorStop(0, "#0c0c0f");
    voidG.addColorStop(0.5, "#0a0a0a");
    voidG.addColorStop(1, "#050506");
    c.fillStyle = voidG;
    c.fillRect(0, 0, w, h);

    // soft nebula only (radial gradients — never hard ellipses)
    function wash(x, y, r, rgba) {
      const g = c.createRadialGradient(x, y, 0, x, y, r);
      g.addColorStop(0, rgba);
      g.addColorStop(1, "rgba(0,0,0,0)");
      c.fillStyle = g;
      c.fillRect(0, 0, w, h);
    }
    wash(w * 0.2, h * 0.25, Math.max(w, h) * 0.35, "rgba(124,58,237,0.035)");
    wash(w * 0.8, h * 0.3, Math.max(w, h) * 0.3, "rgba(160,195,236,0.028)");
    wash(w * 0.5, h * 1.05, Math.max(w, h) * 0.45, "rgba(255,255,255,0.02)");
    if (muted && live) {
      wash(w * 0.5, h * 0.5, Math.max(w, h) * 0.22, "rgba(255,122,23,0.035)");
    }
    // energy bloom (subtle, live only)
    if (live && energy > 0.05) {
      wash(
        w * 0.5,
        h * 0.5,
        Math.max(w, h) * (0.2 + energy * 0.12),
        `rgba(255,255,255,${0.015 + energy * 0.03})`
      );
    }

    // stars only — small points
    const dpr = window.devicePixelRatio || 1;
    for (const s of stars) {
      const drift = t * 0.004 * (s.layer + 1);
      const x = ((s.x + drift * 0.12) % 1) * w;
      const y = ((s.y + drift * 0.03) % 1) * h;
      const tw = 0.6 + 0.4 * Math.sin(t * s.sp + s.tw);
      let a = s.a * tw * (live ? 0.75 + energy * 0.25 : 0.55);
      if (s.layer === 2) a *= 1.2;
      const r = Math.max(0.5, s.r * dpr * (0.55 + s.layer * 0.2));
      c.beginPath();
      c.arc(x, y, r, 0, Math.PI * 2);
      c.fillStyle = `rgba(255,255,255,${Math.min(0.85, a)})`;
      c.fill();
      if (s.layer === 2 && tw > 0.9) {
        c.strokeStyle = `rgba(255,255,255,${a * 0.25})`;
        c.lineWidth = 0.5 * dpr;
        c.beginPath();
        c.moveTo(x - r * 2.5, y);
        c.lineTo(x + r * 2.5, y);
        c.moveTo(x, y - r * 2.5);
        c.lineTo(x, y + r * 2.5);
        c.stroke();
      }
    }

    // soft vignette
    const vig = c.createRadialGradient(
      w * 0.5,
      h * 0.5,
      Math.min(w, h) * 0.28,
      w * 0.5,
      h * 0.5,
      Math.max(w, h) * 0.7
    );
    vig.addColorStop(0, "rgba(0,0,0,0)");
    vig.addColorStop(1, "rgba(0,0,0,0.5)");
    c.fillStyle = vig;
    c.fillRect(0, 0, w, h);
  }

  function paintOrb(dn, up, live, muted, injecting) {
    // Rich idle dial (the good one). Speech = same dial + soft tick/core only
    // — no wild polar curves or spark dots.
    const { w, h } = sizeOrb();
    const c = orbCtx;
    const cx = w / 2;
    const cy = h / 2;
    const t = (performance.now() - state.t0) / 1000;
    const energy = live ? Math.max(dn, up * 0.35) : 0;
    const speaking = live && dn > 0.1 && !muted;
    const idlePulse = 0.12 + 0.08 * Math.sin(t * 0.9);
    const breath = 0.5 + 0.5 * Math.sin(t * 0.85);
    // idle spin locked; speech barely accelerates
    const spin = t * (0.18 + (speaking ? Math.min(0.12, energy * 0.25) : 0));
    const m = Math.min(w, h);
    const drive = speaking ? Math.min(0.35, energy * 0.5) : idlePulse;

    c.clearRect(0, 0, w, h);
    paintCosmos(c, w, h, t, live, speaking ? energy * 0.35 : 0, muted);

    const R = m * 0.36;

    // event-horizon glow
    const halo = c.createRadialGradient(cx, cy, R * 0.12, cx, cy, R * 1.55);
    if (muted && live) {
      halo.addColorStop(0, "rgba(255,122,23,0.09)");
      halo.addColorStop(0.55, "rgba(255,122,23,0.02)");
      halo.addColorStop(1, "rgba(0,0,0,0)");
    } else {
      halo.addColorStop(0, `rgba(255,255,255,${0.04 + drive * 0.06})`);
      halo.addColorStop(0.5, `rgba(255,255,255,${0.015 + drive * 0.02})`);
      halo.addColorStop(1, "rgba(0,0,0,0)");
    }
    c.fillStyle = halo;
    c.beginPath();
    c.arc(cx, cy, R * 1.55, 0, Math.PI * 2);
    c.fill();

    // layered concentric rings — same for idle + speech
    const ringRs = [0.28, 0.42, 0.56, 0.72, 0.88, 1.0];
    for (let i = 0; i < ringRs.length; i++) {
      const rr = R * ringRs[i] * (1 + breath * 0.008 * (i % 2 === 0 ? 1 : -1));
      c.beginPath();
      c.arc(cx, cy, rr, 0, Math.PI * 2);
      c.strokeStyle = `rgba(255,255,255,${0.05 + i * 0.022 + drive * 0.03})`;
      c.lineWidth = Math.max(1, m * (0.0018 + (i === ringRs.length - 1 ? 0.001 : 0)));
      c.stroke();
    }

    // dual tick fields — organic idle always; speech adds a little length
    function paintTicks(count, rBase, lenScale, spinMul, alphaBase) {
      for (let i = 0; i < count; i++) {
        const a = (i / count) * Math.PI * 2 - Math.PI / 2 + spin * spinMul;
        const hi = state.histDn[i % state.histDn.length] || 0;
        const organic =
          0.35 +
          0.65 *
            (0.5 +
              0.5 *
                Math.sin(i * 0.55 + t * 0.7) *
                Math.cos(i * 0.21 - t * 0.4));
        const speechBit = speaking
          ? Math.min(0.35, (hi * 0.5 + energy * 0.2) * 0.7)
          : 0;
        const mix = clamp01(organic * idlePulse * 2.2 + organic * 0.15 + speechBit);
        const major = i % 4 === 0;
        const tickLen = R * lenScale * (0.55 + mix * 0.9 + (major ? 0.15 : 0));
        const r0 = R * rBase;
        const r1 = r0 + tickLen;
        c.beginPath();
        c.moveTo(cx + Math.cos(a) * r0, cy + Math.sin(a) * r0);
        c.lineTo(cx + Math.cos(a) * r1, cy + Math.sin(a) * r1);
        const alpha = Math.min(0.85, alphaBase + mix * 0.5 + (major ? 0.08 : 0));
        if (muted && live) {
          c.strokeStyle = `rgba(255,122,23,${0.18 + mix * 0.4})`;
        } else {
          c.strokeStyle = `rgba(255,255,255,${alpha})`;
        }
        c.lineWidth = Math.max(1, m * 0.0028 * (1 + mix * 0.5 + (major ? 0.25 : 0)));
        c.lineCap = "round";
        c.stroke();
      }
    }
    paintTicks(64, 0.9, 0.2, 0.08, 0.12);
    paintTicks(48, 0.62, 0.1, -0.05, 0.08);

    // calm near-circle polar — idle ripple only; speech barely bumps amp
    const n = 96;
    c.beginPath();
    for (let i = 0; i < n; i++) {
      const a = (i / n) * Math.PI * 2 - Math.PI / 2 + spin * 0.12;
      const v = state.histDn[i % state.histDn.length] || 0;
      const idleR = 0.04 + 0.05 * Math.sin(i * 0.35 + t * 1.1);
      const speechR = speaking ? Math.min(0.05, v * 0.08) : 0;
      const rr = R * (0.78 + idleR * 0.06 + speechR);
      const x = cx + Math.cos(a) * rr;
      const y = cy + Math.sin(a) * rr;
      if (i === 0) c.moveTo(x, y);
      else c.lineTo(x, y);
    }
    c.closePath();
    c.strokeStyle = speaking
      ? `rgba(255,255,255,${0.14 + Math.min(0.12, dn * 0.2)})`
      : "rgba(255,255,255,0.14)";
    c.lineWidth = Math.max(1, m * 0.0035);
    c.stroke();

    // second quiet ring (idle character)
    c.beginPath();
    for (let i = 0; i < n; i++) {
      const a = (i / n) * Math.PI * 2 - Math.PI / 2 - spin * 0.1;
      const idleR = 0.03 * Math.sin(i * 0.5 + t * 0.8);
      const rr = R * (0.52 + idleR * 0.05);
      const x = cx + Math.cos(a) * rr;
      const y = cy + Math.sin(a) * rr;
      if (i === 0) c.moveTo(x, y);
      else c.lineTo(x, y);
    }
    c.closePath();
    c.strokeStyle = "rgba(255,255,255,0.1)";
    c.lineWidth = Math.max(1, m * 0.0025);
    c.stroke();

    // triple orbiting arcs — full idle energy
    for (let o = 0; o < 3; o++) {
      const base = R * (0.34 + o * 0.14);
      const sweep = 0.65 + drive * 0.9 + o * 0.18 + breath * 0.08;
      const ang = spin * (1.15 + o * 0.4) + o * 2.05;
      c.beginPath();
      c.arc(cx, cy, base, ang, ang + sweep);
      c.strokeStyle = `rgba(255,255,255,${0.09 + drive * 0.18 - o * 0.015})`;
      c.lineWidth = Math.max(1.2, m * (0.0045 - o * 0.0006));
      c.lineCap = "round";
      c.stroke();
      c.beginPath();
      c.arc(
        cx,
        cy,
        base * 1.02,
        ang + Math.PI * 0.9,
        ang + Math.PI * 0.9 + sweep * 0.45
      );
      c.strokeStyle = `rgba(255,255,255,${0.04 + drive * 0.06})`;
      c.lineWidth = Math.max(1, m * 0.002);
      c.lineCap = "round";
      c.stroke();
    }

    // core
    const coreR = R * (0.18 + (speaking ? Math.min(0.05, energy * 0.07) : 0.01) + breath * 0.02);
    const coreG = c.createRadialGradient(cx, cy, 0, cx, cy, coreR * 1.7);
    if (!live) {
      coreG.addColorStop(0, "#1a1a20");
      coreG.addColorStop(0.55, "#101014");
      coreG.addColorStop(1, "#0a0a0a");
    } else if (muted) {
      coreG.addColorStop(0, "#2c1810");
      coreG.addColorStop(1, "#0a0a0a");
    } else {
      coreG.addColorStop(0, speaking ? "#222228" : "#1a1a20");
      coreG.addColorStop(1, "#0a0a0a");
    }
    c.beginPath();
    c.arc(cx, cy, coreR * 1.55, 0, Math.PI * 2);
    c.fillStyle = coreG;
    c.fill();

    c.beginPath();
    c.arc(cx, cy, coreR, 0, Math.PI * 2);
    c.strokeStyle = live
      ? muted
        ? "rgba(255,122,23,0.5)"
        : `rgba(255,255,255,${0.2 + (speaking ? Math.min(0.2, dn * 0.25) : 0)})`
      : "rgba(255,255,255,0.16)";
    c.lineWidth = Math.max(1.2, m * 0.004);
    c.stroke();

    c.beginPath();
    c.arc(cx, cy, coreR * 0.55, 0, Math.PI * 2);
    c.strokeStyle = "rgba(255,255,255,0.08)";
    c.lineWidth = Math.max(1, m * 0.002);
    c.stroke();

    const nr = Math.max(2.5, coreR * (0.26 + (speaking ? Math.min(0.1, energy * 0.1) : 0)));
    c.beginPath();
    c.arc(cx, cy, nr, 0, Math.PI * 2);
    c.fillStyle = muted && live ? "#ff7a17" : live ? "#ffffff" : "#9a9ea4";
    c.globalAlpha = live ? 0.92 : 0.62;
    c.fill();
    c.globalAlpha = 1;

    // idle-only glints (2) — never the speech spark storm
    if (!speaking) {
      for (let s = 0; s < 2; s++) {
        const a = spin * 1.9 + (s / 2) * Math.PI * 2;
        const rr = R * (0.7 + 0.08 * Math.sin(t * 2 + s));
        c.beginPath();
        c.arc(
          cx + Math.cos(a) * rr,
          cy + Math.sin(a) * rr,
          Math.max(1, m * 0.0028),
          0,
          Math.PI * 2
        );
        c.fillStyle = "rgba(255,255,255,0.22)";
        c.fill();
      }
    }
  }

  function sizeWave() {
    const dpr = window.devicePixelRatio || 1;
    const rect = el.wave.getBoundingClientRect();
    const w = Math.max(1, Math.floor(rect.width * dpr));
    const h = Math.max(1, Math.floor(Math.max(rect.height, 56) * dpr));
    if (el.wave.width !== w || el.wave.height !== h) {
      el.wave.width = w;
      el.wave.height = h;
    }
  }

  function paintWave() {
    sizeWave();
    const c = waveCtx;
    const w = el.wave.width;
    const h = el.wave.height;
    const mid = h / 2;
    c.clearRect(0, 0, w, h);

    c.strokeStyle = "rgba(255,255,255,0.05)";
    c.beginPath();
    c.moveTo(0, mid);
    c.lineTo(w, mid);
    c.stroke();

    function strokeHist(hist, color, scale) {
      const n = hist.length;
      c.beginPath();
      for (let i = 0; i < n; i++) {
        const x = (i / (n - 1)) * w;
        const y = mid - hist[i] * (h * 0.42) * scale;
        if (i === 0) c.moveTo(x, y);
        else c.lineTo(x, y);
      }
      c.strokeStyle = color;
      c.lineWidth = Math.max(1, (window.devicePixelRatio || 1) * 1.1);
      c.stroke();
    }

    strokeHist(
      state.histDn,
      state.live ? "rgba(218,219,223,0.9)" : "rgba(255,255,255,0.12)",
      1
    );
    strokeHist(
      state.histUp,
      state.muted ? "rgba(255,122,23,0.65)" : "rgba(125,129,135,0.7)",
      0.75
    );
  }

  function setOrbLabel(text, cls) {
    const key = text + "|" + (cls || "");
    if (state.lastOrb === key) return;
    state.lastOrb = key;
    el.orbLabel.textContent = text;
    el.orbLabel.className = "orb-label" + (cls ? " " + cls : "");
  }

  function setText(node, value) {
    if (node && node.textContent !== value) node.textContent = value;
  }

  function setClass(node, value) {
    if (node && node.className !== value) node.className = value;
  }

  function speakingHysteresis(want) {
    // Latch speaking so peaks don't thrash body.speaking every 40ms
    const now = performance.now();
    if (want) {
      state.speakLatch = now;
      return true;
    }
    if (state.speaking && now - state.speakLatch < 450) return true;
    return false;
  }

  function applyMeters(m) {
    m = m || {};
    const status = String(m.status || "idle");
    const live = status === "live";
    state.live = live;
    if (document.body.classList.contains("live") !== live) {
      document.body.classList.toggle("live", live);
    }

    const upRaw = level(m.uplink_peak);
    const dnRaw = level(m.downlink_peak);
    state.up = state.up * 0.55 + upRaw * 0.45;
    state.dn = state.dn * 0.55 + dnRaw * 0.45;
    if (!live) {
      state.up *= 0.92;
      state.dn *= 0.92;
    }

    state.histUp.push(state.up);
    state.histDn.push(state.dn);
    if (state.histUp.length > HISTORY) state.histUp.shift();
    if (state.histDn.length > HISTORY) state.histDn.shift();

    const muted = !!m.muted;
    const injecting = !!m.injecting;
    state.muted = muted;
    state.injecting = injecting;

    const wantSpeak = live && state.dn > 0.14 && !muted;
    const speaking = speakingHysteresis(wantSpeak);
    state.speaking = speaking;
    if (document.body.classList.contains("speaking") !== speaking) {
      document.body.classList.toggle("speaking", speaking);
    }

    if (state.lastStatus !== status) {
      state.lastStatus = status;
      setText(el.status, live ? "live" : status === "stopped" ? "ended" : "idle");
      setClass(
        el.status,
        "chip " + (live ? "chip-live" : status === "stopped" ? "chip-ended" : "chip-idle")
      );
    }

    if (speaking) {
      setOrbLabel("");
    } else if (live && injecting) {
      setOrbLabel("inject", "hot");
    } else if (live && muted) {
      setOrbLabel("muted", "warn");
    } else if (live && state.up > 0.12) {
      setOrbLabel("you");
    } else if (live) {
      setOrbLabel("listen");
    } else if (status === "stopped") {
      setOrbLabel("ended");
    } else {
      setOrbLabel("waiting");
    }

    const muteLabel = muted ? "Unmute" : "Mute";
    if (state.lastMuteLabel !== muteLabel) {
      state.lastMuteLabel = muteLabel;
      setText(el.btnMute, muteLabel);
    }
    setText(el.upPct, Math.round(state.up * 100) + "%");
    setText(el.dnPct, Math.round(state.dn * 100) + "%");

    paintSegs(upSegs, state.up, muted ? "warn" : "normal", "lastSegUp");
    paintSegs(dnSegs, state.dn, "normal", "lastSegDn");

    const tele = {
      session: m.session_name || "—",
      profile: m.profile || "—",
      voice: m.voice || "—",
      mic: muted ? "muted" : live ? m.uplink_src || "open" : "—",
      channel: injecting ? "inject" : m.dc_open ? "dc" : live ? "audio" : "—",
      link: `${m.pc || "—"} / ${m.ice || "—"}`,
    };
    for (const k of Object.keys(tele)) {
      if (state.lastTele[k] !== tele[k]) {
        state.lastTele[k] = tele[k];
        setText(el.tele[k], tele[k]);
      }
    }
    setClass(el.tele.mic, "v" + (muted ? " warn" : ""));
    setClass(el.tele.channel, "v" + (injecting ? " hot" : ""));

    const hint = live
      ? "space mute · f focus · esc end"
      : status === "stopped"
        ? "ended — surface stays open"
        : "waiting for live · f focus";
    if (state.lastHint !== hint) {
      state.lastHint = hint;
      setText(el.hint, hint);
    }
  }

  async function bridgeCall(name, ...args) {
    if (window.pywebview && window.pywebview.api && window.pywebview.api[name]) {
      return await window.pywebview.api[name](...args);
    }
    return null;
  }

  async function fetchMeters() {
    try {
      if (window.pywebview && window.pywebview.api) {
        const m = await window.pywebview.api.get_meters();
        if (m) {
          state.bridge = "pywebview";
          return m;
        }
      }
    } catch (_) {}

    if (window.__BTW_DEMO__) {
      state.bridge = "demo";
      return window.__BTW_DEMO__();
    }

    try {
      const r = await fetch("/meters", { cache: "no-store" });
      if (r.ok) {
        state.bridge = "http";
        return await r.json();
      }
    } catch (_) {}

    return { status: "idle" };
  }

  async function muteToggle() {
    if (state.muted) await bridgeCall("unmute");
    else await bridgeCall("mute");
  }

  async function stopCall() {
    await bridgeCall("stop");
  }

  el.btnMute.addEventListener("click", () => muteToggle());
  el.btnStop.addEventListener("click", () => stopCall());
  if (el.btnView) el.btnView.addEventListener("click", () => toggleFocusMode());
  if (el.btnViewExit) el.btnViewExit.addEventListener("click", () => setFocusMode(false));

  window.addEventListener("keydown", (e) => {
    if (e.code === "Space") {
      e.preventDefault();
      muteToggle();
    } else if (e.code === "KeyF" && !e.metaKey && !e.ctrlKey && !e.altKey) {
      e.preventDefault();
      toggleFocusMode();
    } else if (e.code === "Escape") {
      e.preventDefault();
      if (state.focus) setFocusMode(false);
      else stopCall();
    }
  });

  window.addEventListener("resize", () => {
    fieldKey = "";
    paintOrb(state.dn, state.up, state.live, state.muted, state.injecting);
    paintWave();
  });

  // Continuous paint (smooth dial). Meters only update levels.
  function frame() {
    paintOrb(state.dn, state.up, state.live, state.muted, state.injecting);
    paintWave();
    requestAnimationFrame(frame);
  }

  async function tick() {
    try {
      const m = await fetchMeters();
      applyMeters(m);
    } catch (_) {
      applyMeters({ status: "idle" });
    }
    setTimeout(tick, 50);
  }

  let loopsStarted = false;
  function startLoops() {
    if (loopsStarted) return;
    loopsStarted = true;
    tick();
    requestAnimationFrame(frame);
  }

  window.addEventListener("pywebviewready", () => {
    state.bridge = "pywebview";
    startLoops();
  });

  if (window.pywebview && window.pywebview.api) startLoops();
  else setTimeout(startLoops, 100);
})();
