"""btw Live surface — tkinter fallback (prefer pywebview via btw.viz).

Polls meters.json; mute / unmute / stop via control IPC.
"""
from __future__ import annotations

import json
import math
import os
import time
import tkinter as tk
from tkinter import font as tkfont
from collections import deque
from typing import Any

from .control import push_command, read_meters, viz_pid_path
from .paths import data_dir
from .version import __version__

# ── xAI tokens ──────────────────────────────────────────────────────────────
VOID = "#0a0a0a"
CARD = "#191919"
SOFT = "#1a1c20"
GRAPHITE = "#1f2228"
SMOKE = "#474747"
WHITE = "#ffffff"
INK = "#fafaf7"
BODY = "#dadbdf"
ASH = "#7d8187"
SUNSET = "#ff7a17"  # muted accent — mute / caution only
FOCUS = "#2563eb"  # functional only

POLL_MS = 40
HISTORY = 96
WIN_W = 440
WIN_H = 780

# Layout geometry (px)
ORB_SIZE = 220
SPECT_W = 360
SPECT_H = 28
WAVE_H = 72
SEGMENTS = 32


def _clamp01(x: float) -> float:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return 0.0
    return 0.0 if v < 0.0 else 1.0 if v > 1.0 else v


def _level(peak: float) -> float:
    p = _clamp01(abs(float(peak or 0.0)) * 2.4)
    return p**0.72


def _font(family: str, size: int, **kw: Any) -> tkfont.Font:
    return tkfont.Font(family=family, size=size, weight=kw.get("weight", "normal"))


class Pill(tk.Frame):
    """Outline pill button — xAI interactive shape (canvas child, not Canvas subclass)."""

    def __init__(
        self,
        master: tk.Misc,
        text: str,
        command,
        *,
        filled: bool = False,
        danger: bool = False,
        width: int = 108,
        height: int = 36,
    ):
        super().__init__(master, bg=VOID, width=width, height=height)
        self.pack_propagate(False)
        self._cmd = command
        self._text = text
        self._filled = filled
        self._danger = danger
        self._bw = width
        self._bh = height
        self._hover = False
        self._font = _font("Segoe UI", 10)
        self._can = tk.Canvas(
            self,
            width=width,
            height=height,
            bg=VOID,
            highlightthickness=0,
            cursor="hand2",
        )
        self._can.pack(fill="both", expand=True)
        self._draw()
        for w in (self, self._can):
            w.bind("<Button-1>", lambda _e: self._cmd())
            w.bind("<Enter>", self._on_enter)
            w.bind("<Leave>", self._on_leave)

    def _on_enter(self, _e=None) -> None:
        self._hover = True
        self._draw()

    def _on_leave(self, _e=None) -> None:
        self._hover = False
        self._draw()

    def set_text(self, text: str) -> None:
        if text != self._text:
            self._text = text
            self._draw()

    def _pill_poly(self, pad: float = 1.0) -> list[float]:
        w, h = self._bw, self._bh
        r = (h - 2 * pad) / 2
        cx0, cx1 = pad + r, w - pad - r
        cy = h / 2
        pts: list[float] = []
        steps = 14
        for i in range(steps + 1):
            a = math.pi / 2 + (math.pi * i / steps)
            pts.extend([cx0 + r * math.cos(a), cy - r * math.sin(a)])
        for i in range(steps + 1):
            a = -math.pi / 2 + (math.pi * i / steps)
            pts.extend([cx1 + r * math.cos(a), cy - r * math.sin(a)])
        return pts

    def _draw(self) -> None:
        c = self._can
        c.delete("all")
        if self._filled:
            fill, outline, fg = WHITE, WHITE, VOID
        elif self._danger:
            fill = SOFT if self._hover else VOID
            outline = ASH if self._hover else SMOKE
            fg = WHITE if self._hover else BODY
        else:
            fill = SOFT if self._hover else VOID
            outline = "#555555" if self._hover else "#404040"
            fg = WHITE
        pts = self._pill_poly()
        c.create_polygon(pts, fill=fill, outline=outline, width=1)
        c.create_text(
            self._bw / 2,
            self._bh / 2,
            text=self._text,
            fill=fg,
            font=self._font,
        )


class Card(tk.Frame):
    def __init__(self, master: tk.Misc, **kw: Any):
        super().__init__(
            master,
            bg=CARD,
            highlightbackground=GRAPHITE,
            highlightthickness=1,
            bd=0,
            **kw,
        )


class VizApp:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title(f"btw  ·  live surface  ·  {__version__}")
        self.root.configure(bg=VOID)
        self.root.geometry(f"{WIN_W}x{WIN_H}")
        self.root.minsize(400, 680)
        try:
            self.root.attributes("-topmost", True)
        except tk.TclError:
            pass
        # void chrome
        try:
            self.root.configure(highlightthickness=0)
        except tk.TclError:
            pass

        self._sans = "Segoe UI"
        self._mono = "Cascadia Mono" if self._font_exists("Cascadia Mono") else "Consolas"

        self._up_disp = 0.0
        self._down_disp = 0.0
        self._was_live = False
        self._stop_seen_at: float | None = None
        self._t0 = time.monotonic()
        self._phase = 0.0
        self._hist_up: deque[float] = deque([0.0] * HISTORY, maxlen=HISTORY)
        self._hist_down: deque[float] = deque([0.0] * HISTORY, maxlen=HISTORY)
        self._last_meta: dict[str, Any] = {}
        self._muted = False
        self._live = False

        self._build()
        self._tick()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.bind("<space>", lambda _e: self._toggle_mute())
        self.root.bind("<Escape>", lambda _e: self._stop())
        self.root.bind("m", lambda _e: self._mute())
        self.root.bind("u", lambda _e: self._unmute())

    def _font_exists(self, name: str) -> bool:
        try:
            return name in tkfont.families()
        except Exception:
            return False

    def _build(self) -> None:
        # outer pad
        shell = tk.Frame(self.root, bg=VOID)
        shell.pack(fill="both", expand=True, padx=28, pady=24)

        # ── header ──────────────────────────────────────────
        head = tk.Frame(shell, bg=VOID)
        head.pack(fill="x")

        brand = tk.Frame(head, bg=VOID)
        brand.pack(side="left", fill="x", expand=True)

        tk.Label(
            brand,
            text="BTW",
            font=_font(self._sans, 28),
            fg=WHITE,
            bg=VOID,
            anchor="w",
        ).pack(anchor="w")
        # negative tracking simulated with letter spacing via spaces — real tracking limited in tk
        self.lbl_sub = tk.Label(
            brand,
            text="L I V E   S U R F A C E",
            font=_font(self._mono, 8),
            fg=ASH,
            bg=VOID,
            anchor="w",
        )
        self.lbl_sub.pack(anchor="w", pady=(2, 0))

        self.chip_status = tk.Label(
            head,
            text="  IDLE  ",
            font=_font(self._mono, 9),
            fg=ASH,
            bg=CARD,
            highlightbackground=GRAPHITE,
            highlightthickness=1,
            padx=10,
            pady=6,
        )
        self.chip_status.pack(side="right", anchor="n", pady=(8, 0))

        # hairline
        self._rule(shell, pady=(18, 18))

        # ── hero orb ────────────────────────────────────────
        hero = tk.Frame(shell, bg=VOID)
        hero.pack(fill="x")

        self.orb_can = tk.Canvas(
            hero,
            width=ORB_SIZE,
            height=ORB_SIZE,
            bg=VOID,
            highlightthickness=0,
        )
        self.orb_can.pack()
        self._orb_rings: list[int] = []
        self._orb_core = 0
        self._orb_glow = 0
        self._init_orb()

        self.lbl_orb = tk.Label(
            hero,
            text="WAITING",
            font=_font(self._mono, 9),
            fg=ASH,
            bg=VOID,
        )
        self.lbl_orb.pack(pady=(8, 0))

        # ── spectrum meters ─────────────────────────────────
        meters = Card(shell)
        meters.pack(fill="x", pady=(22, 0))
        inner = tk.Frame(meters, bg=CARD)
        inner.pack(fill="x", padx=18, pady=16)

        self._meter_up = self._build_meter_row(inner, "YOU", "uplink")
        self._rule(inner, pady=(14, 14), color=GRAPHITE, parent_bg=CARD)
        self._meter_down = self._build_meter_row(inner, "HER", "downlink")

        # ── waveform trail ──────────────────────────────────
        wave_card = Card(shell)
        wave_card.pack(fill="x", pady=(12, 0))
        w_inner = tk.Frame(wave_card, bg=CARD)
        w_inner.pack(fill="x", padx=14, pady=12)

        tk.Label(
            w_inner,
            text="TRACE",
            font=_font(self._mono, 8),
            fg=ASH,
            bg=CARD,
            anchor="w",
        ).pack(anchor="w", padx=4)

        self.wave = tk.Canvas(
            w_inner,
            width=SPECT_W,
            height=WAVE_H,
            bg=CARD,
            highlightthickness=0,
        )
        self.wave.pack(fill="x", pady=(6, 0))

        # ── telemetry ───────────────────────────────────────
        tel = Card(shell)
        tel.pack(fill="x", pady=(12, 0))
        t_inner = tk.Frame(tel, bg=CARD)
        t_inner.pack(fill="x", padx=18, pady=14)

        tk.Label(
            t_inner,
            text="TELEMETRY",
            font=_font(self._mono, 8),
            fg=ASH,
            bg=CARD,
            anchor="w",
        ).pack(anchor="w")

        grid = tk.Frame(t_inner, bg=CARD)
        grid.pack(fill="x", pady=(10, 0))

        self._tel: dict[str, tk.Label] = {}
        rows = [
            ("SESSION", "session"),
            ("PROFILE", "profile"),
            ("VOICE", "voice"),
            ("MIC", "mic"),
            ("CHANNEL", "channel"),
            ("PC / ICE", "link"),
            ("UPLINK", "up_peak"),
            ("DOWNLINK", "dn_peak"),
        ]
        for i, (label, key) in enumerate(rows):
            r = i // 2
            c = (i % 2) * 2
            tk.Label(
                grid,
                text=label,
                font=_font(self._mono, 7),
                fg=ASH,
                bg=CARD,
                anchor="w",
            ).grid(row=r * 2, column=c, sticky="w", padx=(0 if c == 0 else 16, 8), pady=(0, 0))
            val = tk.Label(
                grid,
                text="—",
                font=_font(self._sans, 11),
                fg=BODY,
                bg=CARD,
                anchor="w",
            )
            val.grid(row=r * 2 + 1, column=c, sticky="w", padx=(0 if c == 0 else 16, 8), pady=(0, 10))
            self._tel[key] = val
        grid.columnconfigure(0, weight=1)
        grid.columnconfigure(2, weight=1)

        # ── controls ────────────────────────────────────────
        ctrl = tk.Frame(shell, bg=VOID)
        ctrl.pack(fill="x", pady=(20, 0))

        self.btn_mute = Pill(ctrl, "Mute", self._toggle_mute, width=118, height=38)
        self.btn_mute.pack(side="left")

        self.btn_stop = Pill(ctrl, "End call", self._stop, danger=True, width=118, height=38)
        self.btn_stop.pack(side="right")

        # footer
        foot = tk.Frame(shell, bg=VOID)
        foot.pack(fill="x", side="bottom", pady=(16, 0))
        self._rule(foot, pady=(0, 12))
        self.lbl_hint = tk.Label(
            foot,
            text=f"SPACE mute  ·  ESC end  ·  v{__version__}",
            font=_font(self._mono, 7),
            fg=ASH,
            bg=VOID,
        )
        self.lbl_hint.pack()

    def _rule(
        self,
        parent: tk.Misc,
        *,
        pady: tuple[int, int] = (0, 0),
        color: str = GRAPHITE,
        parent_bg: str | None = None,
    ) -> None:
        f = tk.Frame(parent, bg=color, height=1)
        f.pack(fill="x", pady=pady)
        f.pack_propagate(False)

    def _build_meter_row(self, parent: tk.Misc, title: str, kind: str) -> dict[str, Any]:
        row = tk.Frame(parent, bg=CARD)
        row.pack(fill="x")

        top = tk.Frame(row, bg=CARD)
        top.pack(fill="x")
        tk.Label(
            top,
            text=title,
            font=_font(self._mono, 8),
            fg=ASH,
            bg=CARD,
            anchor="w",
        ).pack(side="left")
        pct = tk.Label(
            top,
            text="0%",
            font=_font(self._mono, 8),
            fg=BODY,
            bg=CARD,
            anchor="e",
        )
        pct.pack(side="right")

        can = tk.Canvas(
            row,
            width=SPECT_W,
            height=SPECT_H,
            bg=CARD,
            highlightthickness=0,
        )
        can.pack(fill="x", pady=(8, 0))

        # segment track
        segs: list[int] = []
        gap = 2
        total_gap = gap * (SEGMENTS - 1)
        sw = max(2, (SPECT_W - total_gap) // SEGMENTS)
        for i in range(SEGMENTS):
            x0 = i * (sw + gap)
            rect = can.create_rectangle(
                x0, 4, x0 + sw, SPECT_H - 4, fill=GRAPHITE, outline="", width=0
            )
            segs.append(rect)

        return {"canvas": can, "segs": segs, "pct": pct, "kind": kind, "sw": sw, "gap": gap}

    def _init_orb(self) -> None:
        c = self.orb_can
        c.delete("all")
        cx = cy = ORB_SIZE / 2
        # faint guide rings
        self._orb_rings = []
        for i, r in enumerate((98, 78, 58)):
            oid = c.create_oval(
                cx - r, cy - r, cx + r, cy + r,
                outline=GRAPHITE,
                width=1,
            )
            self._orb_rings.append(oid)
        self._orb_glow = c.create_oval(
            cx - 40, cy - 40, cx + 40, cy + 40,
            fill=SOFT,
            outline=GRAPHITE,
            width=1,
        )
        self._orb_core = c.create_oval(
            cx - 22, cy - 22, cx + 22, cy + 22,
            fill=CARD,
            outline=SMOKE,
            width=1,
        )
        self._orb_dot = c.create_oval(
            cx - 4, cy - 4, cx + 4, cy + 4,
            fill=ASH,
            outline="",
        )

    def _paint_orb(self, level: float, live: bool, muted: bool, injecting: bool) -> None:
        c = self.orb_can
        cx = cy = ORB_SIZE / 2
        t = time.monotonic() - self._t0
        breath = 0.5 + 0.5 * math.sin(t * (2.2 if live else 0.9))

        # ring pulse
        bases = (98, 78, 58)
        for i, oid in enumerate(self._orb_rings):
            pulse = level * (0.18 - i * 0.03) + breath * 0.02 * (1 if live else 0.4)
            r = bases[i] * (1.0 + pulse)
            c.coords(oid, cx - r, cy - r, cx + r, cy + r)
            if live and level > 0.12:
                c.itemconfigure(oid, outline="#3a3a3a" if i else "#4a4a4a")
            else:
                c.itemconfigure(oid, outline=GRAPHITE)

        # core scales with her voice
        cr = 18 + 28 * _clamp01(level) + 4 * breath * (1 if live else 0)
        c.coords(self._orb_core, cx - cr, cy - cr, cx + cr, cy + cr)
        gr = cr + 14 + 10 * _clamp01(level)
        c.coords(self._orb_glow, cx - gr, cy - gr, cx + gr, cy + gr)

        if not live:
            core_f, core_o, glow_f, dot = CARD, SMOKE, SOFT, ASH
        elif muted and level < 0.05:
            core_f, core_o, glow_f, dot = "#1c1410", SUNSET, "#14100c", SUNSET
        elif injecting:
            core_f, core_o, glow_f, dot = "#141820", BODY, SOFT, WHITE
        elif level > 0.1:
            core_f, core_o, glow_f, dot = "#222222", WHITE, "#2a2a2a", WHITE
        else:
            core_f, core_o, glow_f, dot = CARD, SMOKE, SOFT, BODY

        c.itemconfigure(self._orb_core, fill=core_f, outline=core_o)
        c.itemconfigure(self._orb_glow, fill=glow_f, outline=GRAPHITE)
        dr = 3 + 5 * _clamp01(level)
        c.coords(self._orb_dot, cx - dr, cy - dr, cx + dr, cy + dr)
        c.itemconfigure(self._orb_dot, fill=dot)

    def _paint_meter(self, meter: dict[str, Any], level: float, *, hot: bool, caution: bool) -> None:
        segs = meter["segs"]
        n = len(segs)
        lit = int(round(_clamp01(level) * n))
        for i, rid in enumerate(segs):
            if i < lit:
                if caution:
                    fill = SUNSET if i > n * 0.7 else "#c45a12"
                elif hot:
                    # white → soft white gradient by index
                    if i > n * 0.85:
                        fill = WHITE
                    elif i > n * 0.55:
                        fill = BODY
                    else:
                        fill = "#9a9b9f"
                else:
                    fill = SMOKE
            else:
                fill = GRAPHITE
            meter["canvas"].itemconfigure(rid, fill=fill)
        meter["pct"].configure(text=f"{int(_clamp01(level) * 100):3d}%")

    def _paint_wave(self) -> None:
        c = self.wave
        c.delete("all")
        w = max(c.winfo_width(), SPECT_W)
        h = WAVE_H
        mid = h / 2
        # center line
        c.create_line(0, mid, w, mid, fill=GRAPHITE, width=1)

        def poly(hist: deque[float], color: str, scale: float) -> None:
            if len(hist) < 2:
                return
            pts: list[float] = []
            n = len(hist)
            for i, v in enumerate(hist):
                x = (i / (n - 1)) * (w - 1)
                y = mid - v * (h * 0.42) * scale
                pts.extend([x, y])
            # mirror underside for dual trace feel
            for i in range(n - 1, -1, -1):
                v = hist[i]
                x = (i / (n - 1)) * (w - 1)
                y = mid + v * (h * 0.42) * scale * 0.55
                pts.extend([x, y])
            if len(pts) >= 6:
                c.create_polygon(pts, fill="", outline=color, width=1)

        # her on top (brighter), you beneath (ash)
        poly(self._hist_down, BODY if self._live else GRAPHITE, 1.0)
        poly(self._hist_up, ASH if not self._muted else SUNSET, 0.85)

        # right-edge markers
        c.create_text(
            w - 4,
            10,
            text="HER",
            fill=ASH,
            font=_font(self._mono, 6),
            anchor="e",
        )
        c.create_text(
            w - 4,
            h - 8,
            text="YOU",
            fill=ASH,
            font=_font(self._mono, 6),
            anchor="e",
        )

    def _mute(self) -> None:
        push_command("mute")

    def _unmute(self) -> None:
        push_command("unmute")

    def _toggle_mute(self) -> None:
        if self._muted:
            self._unmute()
        else:
            self._mute()

    def _stop(self) -> None:
        push_command("stop")

    def _set_status_chip(self, status: str, live: bool) -> None:
        if live:
            self.chip_status.configure(text="  LIVE  ", fg=VOID, bg=WHITE)
        elif status == "stopped":
            self.chip_status.configure(text="  ENDED  ", fg=BODY, bg=CARD)
        else:
            self.chip_status.configure(text="  IDLE  ", fg=ASH, bg=CARD)

    def _tick(self) -> None:
        m = read_meters()
        status = str(m.get("status") or "idle")
        live = status == "live"
        self._live = live

        if live:
            self._was_live = True
            self._stop_seen_at = None
        elif self._was_live:
            if self._stop_seen_at is None:
                self._stop_seen_at = time.time()
            # stay open on second monitor — do not auto-kill (user parks this window)
            # only soft-grey via labels

        up_raw = _level(m.get("uplink_peak", 0))
        down_raw = _level(m.get("downlink_peak", 0))
        self._up_disp = self._up_disp * 0.5 + up_raw * 0.5
        self._down_disp = self._down_disp * 0.5 + down_raw * 0.5
        if not live:
            self._up_disp *= 0.88
            self._down_disp *= 0.88

        self._hist_up.append(self._up_disp)
        self._hist_down.append(self._down_disp)

        muted = bool(m.get("muted"))
        injecting = bool(m.get("injecting"))
        self._muted = muted
        session = str(m.get("session_name") or "—")
        profile = str(m.get("profile") or "—")
        voice = str(m.get("voice") or "—")
        pc = m.get("pc") or "—"
        ice = m.get("ice") or "—"
        src = m.get("uplink_src") or "—"

        self._set_status_chip(status, live)

        if live and injecting:
            self.lbl_orb.configure(text="INJECTING CONTEXT", fg=BODY)
        elif live and muted:
            self.lbl_orb.configure(text="MIC MUTED", fg=SUNSET)
        elif live and self._down_disp > 0.12:
            self.lbl_orb.configure(text="SHE IS SPEAKING", fg=WHITE)
        elif live and self._up_disp > 0.12:
            self.lbl_orb.configure(text="YOU ARE SPEAKING", fg=BODY)
        elif live:
            self.lbl_orb.configure(text="LISTENING", fg=ASH)
        elif status == "stopped":
            self.lbl_orb.configure(text="CALL ENDED", fg=ASH)
        else:
            self.lbl_orb.configure(text="WAITING FOR LIVE", fg=ASH)

        self.btn_mute.set_text("Unmute" if muted else "Mute")

        self._paint_orb(self._down_disp, live, muted, injecting)
        self._paint_meter(
            self._meter_up,
            self._up_disp,
            hot=live and not muted,
            caution=muted,
        )
        self._paint_meter(
            self._meter_down,
            self._down_disp,
            hot=live,
            caution=False,
        )
        self._paint_wave()

        # telemetry
        self._tel["session"].configure(text=session)
        self._tel["profile"].configure(text=profile)
        self._tel["voice"].configure(text=voice)
        if muted:
            self._tel["mic"].configure(text="muted", fg=SUNSET)
        elif live:
            self._tel["mic"].configure(text=f"open · {src}", fg=BODY)
        else:
            self._tel["mic"].configure(text="—", fg=BODY)
        if injecting:
            self._tel["channel"].configure(text="context inject", fg=WHITE)
        elif m.get("dc_open"):
            self._tel["channel"].configure(text="dc open", fg=BODY)
        else:
            self._tel["channel"].configure(text="audio path", fg=ASH)
        self._tel["link"].configure(text=f"{pc}  /  {ice}")
        self._tel["up_peak"].configure(text=f"{self._up_disp:.2f}")
        self._tel["dn_peak"].configure(text=f"{self._down_disp:.2f}")

        if not live and self._was_live:
            self.lbl_hint.configure(
                text=f"call ended — surface stays open  ·  v{__version__}"
            )
        else:
            self.lbl_hint.configure(
                text=f"SPACE mute  ·  ESC end  ·  park on second display  ·  v{__version__}"
            )

        self.root.after(POLL_MS, self._tick)

    def _on_close(self) -> None:
        try:
            p = viz_pid_path()
            if p.is_file():
                p.unlink(missing_ok=True)
        except Exception:
            pass
        try:
            self.root.destroy()
        except Exception:
            pass

    def run(self) -> None:
        data_dir().mkdir(parents=True, exist_ok=True)
        try:
            viz_pid_path().write_text(str(os.getpid()), encoding="utf-8")
        except Exception:
            pass
        # center-ish default; user drags to second monitor
        try:
            self.root.update_idletasks()
            sw = self.root.winfo_screenwidth()
            sh = self.root.winfo_screenheight()
            x = max(0, (sw - WIN_W) // 2)
            y = max(0, (sh - WIN_H) // 2)
            self.root.geometry(f"{WIN_W}x{WIN_H}+{x}+{y}")
        except Exception:
            pass
        self.root.mainloop()


def main(argv: list[str] | None = None) -> int:
    _ = argv
    try:
        app = VizApp()
        app.run()
    except Exception as e:
        print(json.dumps({"ok": False, "error": str(e)}), flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
