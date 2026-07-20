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
    // hold optimistic mute until meters catch up (prevents 1-frame flash)
    muteHoldUntil: 0,
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
    // sticky last-good meters — empty/failed reads must not paint IDLE for one frame
    lastGood: null,
    missPolls: 0,
    // continuous 0..1 mode mixes (frame-eased — no hard snaps)
    mix: { live: 0, muted: 0, speak: 0, inject: 0, you: 0 },
    tgt: { live: 0, muted: 0, speak: 0, inject: 0, you: 0 },
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
    // Backend already sends 0..1 envelope (RMS+peak). Mild perceptual curve only —
    // old *2.4 made quiet frames dead and spikes peg solid white.
    return Math.pow(clamp01(Math.abs(+peak || 0)), 0.65);
  }

  function smoothToward(cur, target, attack, release) {
    if (target > cur) return cur + (target - cur) * attack;
    return cur + (target - cur) * release;
  }

  function easeMix(cur, target, k, dt) {
    const a = 1 - Math.exp(-k * dt);
    return cur + (target - cur) * a;
  }

  function lerp(a, b, t) {
    return a + (b - a) * clamp01(t);
  }

  function paintSegs(nodes, v, mode, cacheKey) {
    // fractional light for smoother fill (partial last segment via opacity)
    const f = clamp01(v) * SEGS;
    const lit = Math.floor(f);
    const frac = f - lit;
    const key = mode + ":" + lit + ":" + Math.round(frac * 4);
    if (state[cacheKey] === key) return;
    state[cacheKey] = key;
    for (let i = 0; i < SEGS; i++) {
      const n = nodes[i];
      let cls = "seg";
      let opacity = "";
      if (i < lit) {
        cls += " on";
        if (mode === "warn") {
          cls += i > SEGS * 0.7 ? " warn-peak" : " warn";
        } else if (i > SEGS * 0.85) {
          cls += " peak";
        } else if (i > SEGS * 0.5 || mode === "hot") {
          cls += " hot";
        }
      } else if (i === lit && frac > 0.08) {
        cls += " on partial";
        if (mode === "warn") cls += " warn";
        else if (mode === "hot" || i > SEGS * 0.5) cls += " hot";
        opacity = String(0.2 + frac * 0.8);
      }
      if (n.className !== cls) n.className = cls;
      if (n.style.opacity !== opacity) n.style.opacity = opacity;
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
    // clientWidth/Height — no writing CSS size (that fought flex and flashed)
    const cssW = Math.max(200, pane.clientWidth | 0);
    const cssH = Math.max(200, pane.clientHeight | 0);
    const w = Math.floor(cssW * dpr);
    const h = Math.floor(cssH * dpr);
    // Large threshold: setting canvas.width clears the bitmap → one black frame.
    // Ignore sub-pixel / DPI / scrollbar noise completely.
    const dw = Math.abs(el.orb.width - w);
    const dh = Math.abs(el.orb.height - h);
    if ((dw > 12 || dh > 12 || !el.orb.width) && cssW > 0 && cssH > 0) {
      el.orb.width = w;
      el.orb.height = h;
      fieldKey = "";
    }
    return { w: el.orb.width || w, h: el.orb.height || h, dpr };
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

  // Orb reacts to AI downlink only. Mic/mute is chrome (meters + label), not the ring.
  const AI_THRESH = 0.12; // ignore noise floor under this (0–1 after level())

  function aiEnergy(dn) {
    const v = clamp01(dn);
    if (v <= AI_THRESH) return 0;
    // compress hard — speech is on/soft, not a strobe meter
    return Math.pow((v - AI_THRESH) / (1 - AI_THRESH), 0.9);
  }

  function paintOrb(dn, up, live, muted, injecting) {
    // Calm dial: idle motion stays; AI-only global pulse (readable, not thrash).
    // `up` kept for API parity — never mixed into orb energy.
    void up;
    void injecting;
    const { w, h } = sizeOrb();
    const c = orbCtx;
    const cx = w / 2;
    const cy = h / 2;
    const t = (performance.now() - state.t0) / 1000;
    const mx = state.mix;
    const liveM = mx.live;
    const muteM = mx.muted;
    const speakM = mx.speak;
    const energy = liveM > 0.05 ? aiEnergy(dn) * liveM : 0;
    // smoothed speak amount — tracks energy enough that quiet speech still pulses
    const speakSoft = speakM * Math.min(1, 0.45 + energy * 0.7);
    const idlePulse = 0.12 + 0.08 * Math.sin(t * 0.9);
    const breath = 0.5 + 0.5 * Math.sin(t * 0.85);
    // speech-paced breath (clearer than idle-only when she talks)
    const speakBreath = 0.5 + 0.5 * Math.sin(t * 2.15);
    // spin barely accelerates when she talks
    const spin = t * (0.18 + speakSoft * 0.05);
    const m = Math.min(w, h);
    // glow drive lifts with speech so pulse reads on the halo too
    const drive = idlePulse + speakSoft * (0.16 + 0.12 * speakBreath + energy * 0.1);
    // scale pulse ~8–16% peak — clearly readable while she talks
    const pulse =
      1 +
      speakSoft *
        (0.07 + 0.08 * Math.sin(t * 2.15) + energy * 0.035 + speakBreath * 0.02);

    c.clearRect(0, 0, w, h);
    // cosmos bloom lifts a bit with speech; mute wash eases in
    paintCosmos(
      c,
      w,
      h,
      t,
      liveM > 0.2,
      speakSoft * (0.12 + 0.14 * speakSoft + 0.06 * speakBreath),
      muteM > 0.15
    );

    const R = m * 0.36 * pulse;

    // event-horizon glow — stronger when speaking so pulse is obvious
    const halo = c.createRadialGradient(cx, cy, R * 0.12, cx, cy, R * 1.55);
    halo.addColorStop(
      0,
      `rgba(255,255,255,${0.035 + drive * 0.05 + speakSoft * (0.08 + 0.05 * speakBreath)})`
    );
    halo.addColorStop(0.5, `rgba(255,255,255,${0.012 + drive * 0.025 + speakSoft * 0.03})`);
    halo.addColorStop(1, "rgba(0,0,0,0)");
    c.fillStyle = halo;
    c.beginPath();
    c.arc(cx, cy, R * 1.55, 0, Math.PI * 2);
    c.fill();
    // mute wash crossfades with mix (does not freeze pulse)
    if (muteM > 0.02) {
      const muteHalo = c.createRadialGradient(cx, cy, R * 0.1, cx, cy, R * 1.2);
      muteHalo.addColorStop(0, `rgba(255,122,23,${0.055 * muteM * (1 - speakSoft * 0.5)})`);
      muteHalo.addColorStop(1, "rgba(0,0,0,0)");
      c.fillStyle = muteHalo;
      c.beginPath();
      c.arc(cx, cy, R * 1.2, 0, Math.PI * 2);
      c.fill();
    }

    // concentric rings — breathe more while speaking (still even, not jagged)
    const ringRs = [0.28, 0.42, 0.56, 0.72, 0.88, 1.0];
    for (let i = 0; i < ringRs.length; i++) {
      const ringBreath =
        breath * 0.008 + speakSoft * speakBreath * 0.045 * (i % 2 === 0 ? 1 : -1);
      const rr = R * ringRs[i] * (1 + ringBreath);
      c.beginPath();
      c.arc(cx, cy, rr, 0, Math.PI * 2);
      c.strokeStyle = `rgba(255,255,255,${0.05 + i * 0.022 + drive * 0.03 + speakSoft * 0.045})`;
      c.lineWidth = Math.max(1, m * (0.0018 + (i === ringRs.length - 1 ? 0.001 : 0)));
      c.stroke();
    }

    // dual tick fields — organic idle only; speech does NOT thrash tick lengths
    function paintTicks(count, rBase, lenScale, spinMul, alphaBase) {
      for (let i = 0; i < count; i++) {
        const a = (i / count) * Math.PI * 2 - Math.PI / 2 + spin * spinMul;
        const organic =
          0.35 +
          0.65 *
            (0.5 +
              0.5 *
                Math.sin(i * 0.55 + t * 0.7) *
                Math.cos(i * 0.21 - t * 0.4));
        const mix = clamp01(organic * idlePulse * 2.2 + organic * 0.15);
        const major = i % 4 === 0;
        const tickLen = R * lenScale * (0.55 + mix * 0.9 + (major ? 0.15 : 0));
        const r0 = R * rBase;
        const r1 = r0 + tickLen;
        c.beginPath();
        c.moveTo(cx + Math.cos(a) * r0, cy + Math.sin(a) * r0);
        c.lineTo(cx + Math.cos(a) * r1, cy + Math.sin(a) * r1);
        const alpha = Math.min(0.75, alphaBase + mix * 0.45 + (major ? 0.06 : 0));
        c.strokeStyle = `rgba(255,255,255,${alpha})`;
        c.lineWidth = Math.max(1, m * 0.0028 * (1 + mix * 0.45 + (major ? 0.2 : 0)));
        c.lineCap = "round";
        c.stroke();
      }
    }
    paintTicks(64, 0.9, 0.2, 0.08, 0.12);
    paintTicks(48, 0.62, 0.1, -0.05, 0.08);

    // calm near-circle polar — no histDn jagged contour while speaking
    const n = 96;
    c.beginPath();
    for (let i = 0; i < n; i++) {
      const a = (i / n) * Math.PI * 2 - Math.PI / 2 + spin * 0.12;
      const idleR = 0.04 + 0.05 * Math.sin(i * 0.35 + t * 1.1);
      const rr = R * (0.78 + idleR * 0.06);
      const x = cx + Math.cos(a) * rr;
      const y = cy + Math.sin(a) * rr;
      if (i === 0) c.moveTo(x, y);
      else c.lineTo(x, y);
    }
    c.closePath();
    c.strokeStyle = "rgba(255,255,255,0.14)";
    c.lineWidth = Math.max(1, m * 0.0035);
    c.stroke();

    // second quiet ring
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

    // orbiting arcs — slight sweep/alpha lift while speaking (still smooth)
    for (let o = 0; o < 3; o++) {
      const base = R * (0.34 + o * 0.14);
      const sweep =
        0.65 +
        idlePulse * 0.75 +
        o * 0.18 +
        breath * 0.08 +
        speakSoft * (0.12 + 0.1 * speakBreath);
      const ang = spin * (1.15 + o * 0.4) + o * 2.05;
      c.beginPath();
      c.arc(cx, cy, base, ang, ang + sweep);
      c.strokeStyle = `rgba(255,255,255,${0.09 + idlePulse * 0.12 + speakSoft * 0.1 - o * 0.015})`;
      c.lineWidth = Math.max(1.2, m * (0.0045 - o * 0.0006 + speakSoft * 0.0008));
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
      c.strokeStyle = `rgba(255,255,255,${0.04 + idlePulse * 0.04 + speakSoft * 0.04})`;
      c.lineWidth = Math.max(1, m * 0.002);
      c.lineCap = "round";
      c.stroke();
    }

    // core — clearer breath when speaking; nucleus eases white↔sunset on mute
    const coreR =
      R *
      (0.18 +
        0.01 +
        breath * 0.02 +
        speakSoft * (0.055 + 0.06 * speakBreath + energy * 0.03));
    const coreG = c.createRadialGradient(cx, cy, 0, cx, cy, coreR * 1.7);
    const coreTop = liveM < 0.15 ? "#1a1a20" : speakSoft > 0.2 ? "#26262c" : "#1a1a20";
    coreG.addColorStop(0, coreTop);
    if (liveM < 0.15) coreG.addColorStop(0.55, "#101014");
    coreG.addColorStop(1, "#0a0a0a");
    c.beginPath();
    c.arc(cx, cy, coreR * 1.55, 0, Math.PI * 2);
    c.fillStyle = coreG;
    c.fill();

    c.beginPath();
    c.arc(cx, cy, coreR, 0, Math.PI * 2);
    c.strokeStyle = `rgba(255,255,255,${lerp(0.16, 0.26 + speakSoft * 0.18, liveM)})`;
    c.lineWidth = Math.max(1.2, m * 0.004);
    c.stroke();

    c.beginPath();
    c.arc(cx, cy, coreR * 0.55, 0, Math.PI * 2);
    c.strokeStyle = `rgba(255,255,255,${0.08 + speakSoft * 0.1})`;
    c.lineWidth = Math.max(1, m * 0.002);
    c.stroke();

    const nr = Math.max(2.5, coreR * (0.26 + speakSoft * (0.09 + 0.06 * speakBreath)));
    // blend nucleus color by mute mix (smooth mute transition)
    const nw = Math.round(lerp(255, 255, muteM));
    const ng = Math.round(lerp(255, 122, muteM));
    const nb = Math.round(lerp(255, 23, muteM));
    const idleGrey = 154;
    const fr = Math.round(lerp(idleGrey, nw, liveM));
    const fg = Math.round(lerp(idleGrey, ng, liveM));
    const fb = Math.round(lerp(164, nb, liveM));
    c.beginPath();
    c.arc(cx, cy, nr, 0, Math.PI * 2);
    c.fillStyle = `rgb(${fr},${fg},${fb})`;
    c.globalAlpha = lerp(0.62, 0.9 + speakSoft * 0.1, liveM);
    c.fill();
    c.globalAlpha = 1;

    // quiet glints always — no speech spark storm
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
      c.fillStyle = `rgba(255,255,255,${lerp(0.22, 0.14, speakSoft)})`;
      c.fill();
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

    const liveA = 0.12 + state.mix.live * 0.78;
    const muteA = state.mix.muted;
    const upR = Math.round(lerp(125, 255, muteA));
    const upG = Math.round(lerp(129, 122, muteA));
    const upB = Math.round(lerp(135, 23, muteA));
    const upA = 0.55 + muteA * 0.1;
    strokeHist(
      state.histDn,
      `rgba(218,219,223,${liveA})`,
      1
    );
    strokeHist(
      state.histUp,
      `rgba(${upR},${upG},${upB},${upA})`,
      0.75
    );
  }

  function setOrbLabel(text, cls) {
    const key = text + "|" + (cls || "");
    if (state.lastOrb === key) return;
    state.lastOrb = key;
    const node = el.orbLabel;
    if (!node) return;
    // crossfade label text
    node.classList.add("orb-label-fade");
    window.setTimeout(() => {
      node.textContent = text;
      node.className =
        "orb-label" + (cls ? " " + cls : "") + " orb-label-fade";
      requestAnimationFrame(() => {
        node.classList.remove("orb-label-fade");
      });
    }, 90);
  }

  function setText(node, value) {
    if (node && node.textContent !== value) node.textContent = value;
  }

  function setClass(node, value) {
    if (node && node.className !== value) node.className = value;
  }

  function speakingHysteresis(want) {
    // Long latch — soft speak mix; avoids label/orb thrash
    const now = performance.now();
    if (want) {
      state.speakLatch = now;
      return true;
    }
    if (state.speaking && now - state.speakLatch < 1100) return true;
    return false;
  }

  function isMeterPayload(m) {
    return !!(m && typeof m === "object" && m.status);
  }

  function applyMeters(m) {
    // Drop empty / failed polls — never paint the IDLE "—" frame from a race.
    if (!isMeterPayload(m)) {
      state.missPolls += 1;
      if (state.lastGood && state.missPolls < 8) {
        // keep last live chrome; only soft-decay levels
        state.up *= 0.97;
        state.dn *= 0.97;
        return;
      }
      if (!state.lastGood) m = { status: "idle" };
      else m = state.lastGood;
    } else {
      const st = String(m.status);
      // One-frame idle/garbage while Live is up: require consecutive non-live
      if (st !== "live" && st !== "stopped" && state.live) {
        state.missPolls += 1;
        if (state.missPolls < 5 && state.lastGood) {
          m = state.lastGood;
        } else {
          state.missPolls = 0;
          state.lastGood = m;
        }
      } else {
        state.missPolls = 0;
        state.lastGood = m;
      }
    }

    m = m || { status: "idle" };
    const status = String(m.status || "idle");
    const live = status === "live";
    state.live = live;
    if (document.body.classList.contains("live") !== live) {
      document.body.classList.toggle("live", live);
    }

    const upRaw = level(m.uplink_peak);
    const dnRaw = level(m.downlink_peak);
    // Softer envelopes — less blink, smoother bars
    state.up = smoothToward(state.up, upRaw, 0.32, 0.12);
    state.dn = smoothToward(state.dn, dnRaw, 0.32, 0.12);
    if (!live) {
      state.up *= 0.92;
      state.dn *= 0.92;
    }

    state.histUp.push(state.up);
    state.histDn.push(state.dn);
    if (state.histUp.length > HISTORY) state.histUp.shift();
    if (state.histDn.length > HISTORY) state.histDn.shift();

    const serverMuted = !!m.muted;
    const injecting = !!m.injecting;
    // Optimistic mute: ignore stale server until hold expires or it matches
    const now = performance.now();
    if (now < state.muteHoldUntil) {
      if (serverMuted === state.muted) state.muteHoldUntil = 0;
      // keep state.muted (optimistic)
    } else {
      state.muted = serverMuted;
    }
    const muted = state.muted;
    state.injecting = injecting;

    // AI-only speaking latch (mute is mic uplink only — does not suppress this)
    const wantSpeak = live && state.dn > AI_THRESH;
    const speaking = speakingHysteresis(wantSpeak);
    state.speaking = speaking;

    // targets for continuous mixes (frame loop eases these)
    state.tgt.live = live ? 1 : 0;
    state.tgt.muted = live && muted ? 1 : 0;
    state.tgt.speak = live && speaking ? 1 : 0;
    state.tgt.inject = live && injecting ? 1 : 0;
    state.tgt.you =
      live && !muted && state.up > 0.1 && !speaking ? 1 : 0;

    // body classes for CSS transitions (chip, mute btn, meta)
    document.body.classList.toggle("live", live);
    document.body.classList.toggle("speaking", speaking);
    document.body.classList.toggle("muted", live && muted);
    document.body.classList.toggle("injecting", live && injecting);

    if (state.lastStatus !== status) {
      state.lastStatus = status;
      setText(el.status, live ? "live" : status === "stopped" ? "ended" : "idle");
      setClass(
        el.status,
        "chip " + (live ? "chip-live" : status === "stopped" ? "chip-ended" : "chip-idle")
      );
    }

    // AI label wins over mute — ring is her voice; mute is my mic (meters show it)
    if (live && injecting) {
      setOrbLabel("inject", "hot");
    } else if (live && speaking) {
      setOrbLabel("ai", "hot");
    } else if (live && muted) {
      setOrbLabel("muted", "warn");
    } else if (live && state.up > 0.1) {
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
    if (el.btnMute) {
      el.btnMute.classList.toggle("pill-muted", live && muted);
      el.btnMute.setAttribute("aria-pressed", muted ? "true" : "false");
    }
    setText(el.upPct, Math.round(state.up * 100) + "%");
    setText(el.dnPct, Math.round(state.dn * 100) + "%");

    // segs: warn mode follows muted mix > half so color eases with mute
    paintSegs(
      upSegs,
      state.up,
      state.mix.muted > 0.45 ? "warn" : "normal",
      "lastSegUp"
    );
    paintSegs(dnSegs, state.dn, speaking ? "hot" : "normal", "lastSegDn");

    // Only write tele when payload has real session fields — never flash "—"
    const hasSession = !!(m.session_name || m.profile || m.voice);
    if (hasSession || !live) {
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
    }

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
        if (isMeterPayload(m)) {
          state.bridge = "pywebview";
          return m;
        }
        // empty {} from read race — keep sticky
        if (m && typeof m === "object") return null;
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
        const m = await r.json();
        return isMeterPayload(m) ? m : null;
      }
    } catch (_) {}

    return null;
  }

  async function muteToggle() {
    // Optimistic + hold so next meter poll cannot flash the old mute for a frame
    const next = !state.muted;
    state.muted = next;
    state.muteHoldUntil = performance.now() + 900;
    state.tgt.muted = state.live && next ? 1 : 0;
    // snap mute mix toward target so chrome doesn't ease reverse for a frame
    state.mix.muted = state.tgt.muted;
    document.body.classList.toggle("muted", state.live && next);
    if (el.btnMute) {
      el.btnMute.classList.toggle("pill-muted", state.live && next);
      setText(el.btnMute, next ? "Unmute" : "Mute");
      state.lastMuteLabel = next ? "Unmute" : "Mute";
      el.btnMute.setAttribute("aria-pressed", next ? "true" : "false");
    }
    if (next) setOrbLabel("muted", "warn");
    else if (state.speaking) setOrbLabel("ai", "hot");
    else if (state.live) setOrbLabel("listen");
    try {
      if (next) await bridgeCall("mute");
      else await bridgeCall("unmute");
    } catch (_) {}
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

  // Continuous paint: ease mode mixes then draw (mute / speak / live / inject)
  let lastFrameT = performance.now();
  function frame(now) {
    const dt = Math.min(0.05, Math.max(0.008, (now - lastFrameT) / 1000));
    lastFrameT = now;
    // slightly different rates so layers don't snap in lockstep
    state.mix.live = easeMix(state.mix.live, state.tgt.live, 5.2, dt);
    state.mix.muted = easeMix(state.mix.muted, state.tgt.muted, 4.0, dt);
    state.mix.speak = easeMix(state.mix.speak, state.tgt.speak, 3.4, dt);
    state.mix.inject = easeMix(state.mix.inject, state.tgt.inject, 4.2, dt);
    state.mix.you = easeMix(state.mix.you, state.tgt.you, 3.8, dt);

    paintOrb(state.dn, state.up, state.live, state.muted, state.injecting);
    paintWave();
    // segs warn blend tracks mute mix continuously
    if (state.live) {
      paintSegs(
        upSegs,
        state.up,
        state.mix.muted > 0.45 ? "warn" : "normal",
        "lastSegUp"
      );
    }
    requestAnimationFrame(frame);
  }

  async function tick() {
    try {
      const m = await fetchMeters();
      applyMeters(m); // null → sticky last-good, no IDLE flash
    } catch (_) {
      applyMeters(null);
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
