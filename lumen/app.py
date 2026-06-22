"""Lumen — main application window."""

from __future__ import annotations

import sys
import threading
import time
import tkinter as tk
from pathlib import Path

import customtkinter as ctk
from PIL import Image

from . import __version__
from .autostart import is_autostart_enabled, set_autostart
from .backends import get_backend
from .config import (
    DEFAULT_PRESETS,
    Binding,
    GameRule,
    Profile,
    load_settings,
    save_settings,
)
from .engine import (
    BRIGHTNESS_MAX,
    BRIGHTNESS_MIN,
    GAMMA_MAX,
    GAMMA_MIN,
    TEMP_DEFAULT,
    TEMP_MAX,
    TEMP_MIN,
    GammaRamp,
    clamp_brightness,
    clamp_gamma,
    clamp_temperature,
    temperature_to_rgb,
)
from .hotkeys import (
    KeyboardManager,
    MouseDispatcher,
    format_hotkey,
    hotkeys_available,
    mouse_available,
)
from .widgets import GlowSlider, GradientPanel, RadialDial
from . import resolution as resmod
from .automation import AppWatcher, normalize_name
from .vibrance import get_vibrance_backend
from . import theme as T

try:
    import pystray
    from PIL import ImageDraw
    _HAS_TRAY = True
except Exception:
    _HAS_TRAY = False

APP_NAME = "Lumen"


def asset(name: str) -> Path:
    try:
        base = Path(sys._MEIPASS)  # type: ignore[attr-defined]
        p = base / "lumen" / "assets" / name
        if p.exists():
            return p
        p = base / name
        if p.exists():
            return p
    except Exception:
        pass
    return Path(__file__).resolve().parent / "assets" / name


class LumenApp:
    def __init__(self, start_hidden: bool = False):
        self.settings = load_settings().normalized()
        self.accent = T.Accent(self.settings.accent)
        self.backend = get_backend()
        self.monitors = self.backend.list_monitors()
        self.monitor_labels = [m.label for m in self.monitors]

        self.cur_gamma = self.settings.gamma
        self.cur_brightness = self.settings.brightness
        self.cur_temp = self.settings.temperature

        self.vibrance = get_vibrance_backend()
        self.cur_vibrance = self.settings.vibrance
        self._primary = next((m for m in self.monitors if m.primary), self.monitors[0])
        self._res_revert_job = None
        self._res_prev_mode = None
        self._rule_saved_vibrance = None
        self._rule_saved_mode = None
        self._watcher = AppWatcher(self._on_app_start, self._on_app_stop)

        self._kb = KeyboardManager()
        self._mouse = MouseDispatcher()
        self._recording = False
        self._pending_hotkey = ""
        self._record_ts = 0.0
        self._last_toggle = 0.0
        self._programmatic = False
        self._anim_token = 0
        self._tray = None
        self._quitting = False
        self._sched_after = None

        ctk.set_appearance_mode("Dark")
        self.root = ctk.CTk(fg_color=T.BG)
        self.root.title(APP_NAME)
        self.root.geometry("900x600")
        self.root.minsize(820, 560)
        try:
            self.root.iconbitmap(str(asset("lumen.ico")))
        except Exception:
            pass
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", self.settings.keep_on_top)
        self.root.protocol("WM_DELETE_WINDOW", self.hide_to_tray)

        # tk vars
        self.v_apply_all = tk.BooleanVar(value=self.settings.apply_all_monitors)
        self.v_restore = tk.BooleanVar(value=self.settings.restore_on_exit)
        self.v_on_top = tk.BooleanVar(value=self.settings.keep_on_top)
        self.v_min = tk.BooleanVar(value=self.settings.start_minimized)
        self.v_smooth = tk.BooleanVar(value=self.settings.smooth_transitions)
        self.v_autostart = tk.BooleanVar(value=is_autostart_enabled())
        self.v_sched = tk.BooleanVar(value=self.settings.schedule_enabled)
        self.v_bind_type = ctk.StringVar(value="Keyboard")

        self.pages: dict[str, ctk.CTkFrame] = {}
        self.nav_btns: dict[str, ctk.CTkButton] = {}

        self._build()
        self._select_monitor_initial()
        self._render_bindings()
        self._rebind_all()
        self.apply_profile(
            Profile("Startup", self.cur_gamma, self.cur_brightness, self.cur_temp),
            animate=False, save=False, announce=False,
        )
        if self.vibrance.available():
            self.vibrance.set_percent(self.cur_vibrance)
        self._start_scheduler()
        self._refresh_watcher()
        self._watcher.start()

        if start_hidden or self.settings.start_minimized:
            self.root.after(200, self.hide_to_tray)

    # ════════════════════════════════════════════════════════════════════
    # Layout
    # ════════════════════════════════════════════════════════════════════
    def _build(self):
        shell = ctk.CTkFrame(self.root, fg_color=T.SURF, corner_radius=0,
                             border_width=1, border_color=T.BORDER)
        shell.pack(fill="both", expand=True)
        shell.grid_columnconfigure(1, weight=1)
        shell.grid_rowconfigure(0, weight=1)

        self._build_sidebar(shell)

        right = ctk.CTkFrame(shell, fg_color="transparent")
        right.grid(row=0, column=1, sticky="nsew")
        right.grid_rowconfigure(1, weight=1)
        right.grid_columnconfigure(0, weight=1)

        self._build_titlebar(right)

        self.content = ctk.CTkFrame(right, fg_color="transparent")
        self.content.grid(row=1, column=0, sticky="nsew")
        self.content.grid_rowconfigure(0, weight=1)
        self.content.grid_columnconfigure(0, weight=1)

        for name in ("Control", "Display", "Hotkeys", "Games", "Schedule", "Settings"):
            page = ctk.CTkFrame(self.content, fg_color="transparent")
            page.grid(row=0, column=0, sticky="nsew")
            self.pages[name] = page

        self._build_control(self.pages["Control"])
        self._build_display(self.pages["Display"])
        self._build_hotkeys(self.pages["Hotkeys"])
        self._build_games(self.pages["Games"])
        self._build_schedule(self.pages["Schedule"])
        self._build_settings(self.pages["Settings"])

        self._status_lbl = ctk.CTkLabel(
            right, text="Ready", text_color=T.MUTED, anchor="w",
            font=T.f(11), height=24,
        )
        self._status_lbl.grid(row=2, column=0, sticky="ew", padx=20, pady=(0, 6))

        self._goto("Control")

    def _build_sidebar(self, parent):
        bar = ctk.CTkFrame(parent, fg_color=T.SURF2, corner_radius=0, width=190)
        bar.grid(row=0, column=0, sticky="nsew")
        bar.grid_propagate(False)

        logo_row = ctk.CTkFrame(bar, fg_color="transparent")
        logo_row.pack(fill="x", padx=18, pady=(22, 6))
        try:
            img = ctk.CTkImage(Image.open(asset("lumen_256.png")), size=(34, 34))
            ctk.CTkLabel(logo_row, image=img, text="").pack(side="left")
            self._logo_img = img
        except Exception:
            ctk.CTkLabel(logo_row, text="\u25D0", text_color=self.accent.main,
                         font=T.f(26, "bold")).pack(side="left")
        name_box = ctk.CTkFrame(logo_row, fg_color="transparent")
        name_box.pack(side="left", padx=(10, 0))
        ctk.CTkLabel(name_box, text="Lumen", text_color=T.TEXT,
                     font=T.f(17, "bold", heavy=True)).pack(anchor="w")
        ctk.CTkLabel(name_box, text=f"v{__version__}", text_color=T.MUTED2,
                     font=T.f(9)).pack(anchor="w")

        ctk.CTkFrame(bar, fg_color=T.BORDER, height=1).pack(fill="x", padx=16, pady=(12, 10))

        nav = [("Control", "\u25D1"), ("Display", "\u25A3"), ("Hotkeys", "\u2328"),
               ("Games", "\u25B6"), ("Schedule", "\u23F0"), ("Settings", "\u2699")]
        for name, icon in nav:
            btn = ctk.CTkButton(
                bar, text=f"   {icon}   {name}", anchor="w", height=40,
                fg_color="transparent", hover_color=T.SURF3,
                text_color=T.MUTED, corner_radius=10, font=T.f(13),
                command=lambda n=name: self._goto(n),
            )
            btn.pack(fill="x", padx=12, pady=2)
            self.nav_btns[name] = btn

        spacer = ctk.CTkFrame(bar, fg_color="transparent")
        spacer.pack(fill="both", expand=True)

        self._backend_lbl = ctk.CTkLabel(
            bar, text=f"Engine: {self.backend.name}", text_color=T.MUTED2,
            font=T.f(9), anchor="w", justify="left", wraplength=160,
        )
        self._backend_lbl.pack(fill="x", padx=18, pady=(0, 16))

    def _build_titlebar(self, parent):
        bar = ctk.CTkFrame(parent, fg_color="transparent", height=46)
        bar.grid(row=0, column=0, sticky="ew")
        bar.grid_propagate(False)

        self._page_title = ctk.CTkLabel(bar, text="Control", text_color=T.TEXT,
                                        font=T.f(15, "bold", heavy=True))
        self._page_title.pack(side="left", padx=22, pady=10)

        def start_move(e):
            self._ox, self._oy = e.x_root, e.y_root
            self._wx, self._wy = self.root.winfo_x(), self.root.winfo_y()

        def do_move(e):
            self.root.geometry(f"+{self._wx + e.x_root - self._ox}+{self._wy + e.y_root - self._oy}")

        for w in (bar, self._page_title):
            w.bind("<Button-1>", start_move)
            w.bind("<B1-Motion>", do_move)

        ctrl = ctk.CTkFrame(bar, fg_color="transparent")
        ctrl.pack(side="right", padx=12)
        ctk.CTkButton(ctrl, text="\u2014", width=32, height=30, fg_color="transparent",
                      hover_color=T.SURF3, text_color=T.MUTED, corner_radius=8,
                      font=T.f(13), command=self.hide_to_tray).pack(side="left", padx=2)
        ctk.CTkButton(ctrl, text="\u2715", width=32, height=30, fg_color="transparent",
                      hover_color=self.accent.danger_bg, text_color=T.DANGER, corner_radius=8,
                      font=T.f(13), command=self._quit).pack(side="left")

    def _goto(self, name: str):
        self.pages[name].tkraise()
        self._page_title.configure(text=name)
        for n, btn in self.nav_btns.items():
            if n == name:
                btn.configure(text_color=self.accent.main, fg_color=T.SURF3)
            else:
                btn.configure(text_color=T.MUTED, fg_color="transparent")

    # ════════════════════════════════════════════════════════════════════
    # Control page
    # ════════════════════════════════════════════════════════════════════
    def _build_control(self, parent):
        wrap = ctk.CTkScrollableFrame(parent, fg_color="transparent",
                                      scrollbar_button_color=T.BORDER,
                                      scrollbar_button_hover_color=T.BORDER2)
        wrap.pack(fill="both", expand=True, padx=14, pady=(0, 4))
        self._slider_widgets = {}

        # Display selector
        top = ctk.CTkFrame(wrap, fg_color=T.SURF2, corner_radius=14)
        top.pack(fill="x", pady=(8, 12))
        ctk.CTkLabel(top, text="DISPLAY", text_color=T.MUTED2, font=T.f(9),
                     anchor="w").pack(anchor="w", padx=16, pady=(12, 4))
        self.monitor_combo = ctk.CTkOptionMenu(
            top, values=self.monitor_labels, fg_color=T.SURF3, button_color=T.SURF3,
            button_hover_color=T.BORDER2, text_color=T.TEXT, dropdown_fg_color=T.SURF3,
            dropdown_hover_color=T.SURF2, dropdown_text_color=T.TEXT,
            corner_radius=8, font=T.f(12), dynamic_resizing=False,
            command=self._on_monitor_change,
        )
        self.monitor_combo.pack(fill="x", padx=16, pady=(0, 14))

        # Hero: gamma dial + preview/brightness/temperature
        hero = ctk.CTkFrame(wrap, fg_color=T.SURF2, corner_radius=18)
        hero.pack(fill="x", pady=(0, 12))
        hero.grid_columnconfigure(1, weight=1)

        self._dial = RadialDial(
            hero, size=216, lo=GAMMA_MIN, hi=GAMMA_MAX, value=self.cur_gamma,
            bg=T.SURF2, accent_dim=self.accent.dim, accent=self.accent.main,
            accent_bright=self.accent.bright, on_change=self._on_gamma,
            fmt=lambda v: f"{v:.2f}", caption="GAMMA")
        self._dial.grid(row=0, column=0, padx=(14, 6), pady=14)
        self._slider_widgets["gamma"] = (self._dial, None, lambda v: f"{v:.2f}")

        right = ctk.CTkFrame(hero, fg_color="transparent")
        right.grid(row=0, column=1, sticky="nsew", padx=(6, 18), pady=18)
        right.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(right, text="LIVE PREVIEW", text_color=T.MUTED2,
                     font=T.f(9)).pack(anchor="w")
        self._preview_panel = GradientPanel(
            right, width=360, height=64, bg=T.SURF2, gamma=self.cur_gamma,
            brightness=self.cur_brightness, temperature=self.cur_temp)
        self._preview_panel.pack(fill="x", pady=(5, 16))

        self._slider_row(right, "BRIGHTNESS", "brightness", BRIGHTNESS_MIN,
                         BRIGHTNESS_MAX, self.cur_brightness,
                         lambda v: f"{int(v * 100)}%", self._on_brightness)
        self._slider_row(right, "TEMPERATURE", "temperature", TEMP_MIN, TEMP_MAX,
                         self.cur_temp, lambda v: f"{int(v)}K", self._on_temp)

        head = ctk.CTkFrame(wrap, fg_color="transparent")
        head.pack(fill="x", pady=(6, 6))
        ctk.CTkLabel(head, text="PRESETS", text_color=T.MUTED2, font=T.f(9)).pack(side="left", padx=2)
        ctk.CTkButton(head, text="reset all", width=64, height=24, fg_color=T.SURF3,
                      hover_color=T.BORDER2, text_color=T.MUTED, corner_radius=8,
                      font=T.f(10), command=self._reset_all).pack(side="right", padx=2)
        self._preset_frame = ctk.CTkFrame(wrap, fg_color="transparent")
        self._preset_frame.pack(fill="x")
        self._render_presets()

    def _slider_row(self, parent, label, kind, lo, hi, value, fmt, cmd):
        head = ctk.CTkFrame(parent, fg_color="transparent")
        head.pack(fill="x", pady=(4, 0))
        ctk.CTkLabel(head, text=label, text_color=T.MUTED2, font=T.f(9)).pack(side="left")
        pill = ctk.CTkLabel(head, text=fmt(value), text_color=self.accent.main,
                            fg_color=T.SURF3, corner_radius=8, font=T.f(12, "bold"),
                            width=58, height=22)
        pill.pack(side="right")
        sl = GlowSlider(parent, width=360, height=40, lo=lo, hi=hi, value=value,
                        kind=kind, bg=T.SURF2, accent=self.accent.main,
                        accent_bright=self.accent.bright, on_change=cmd)
        sl.pack(fill="x", pady=(4, 12))
        self._slider_widgets[kind] = (sl, pill, fmt)

    def _render_presets(self):
        for w in self._preset_frame.winfo_children():
            w.destroy()
        cols = 3
        for i, preset in enumerate(DEFAULT_PRESETS):
            active = (abs(preset.gamma - self.cur_gamma) < 0.02 and
                      abs(preset.brightness - self.cur_brightness) < 0.02 and
                      abs(preset.temperature - self.cur_temp) < 60)
            card = ctk.CTkFrame(
                self._preset_frame,
                fg_color=self.accent.dim if active else T.SURF2,
                corner_radius=12, border_width=1,
                border_color=self.accent.main if active else T.SURF2)
            r, c = divmod(i, cols)
            card.grid(row=r, column=c, padx=4, pady=4, sticky="ew")
            inner = ctk.CTkFrame(card, fg_color="transparent")
            inner.pack(fill="x", padx=12, pady=9)
            rm, gm, bm = temperature_to_rgb(int(preset.temperature))
            dot = f"#{int(rm*255):02x}{int(gm*255):02x}{int(bm*255):02x}"
            ctk.CTkLabel(inner, text="\u25CF", text_color=dot,
                         font=T.f(13)).pack(side="left", padx=(0, 8))
            txt = ctk.CTkFrame(inner, fg_color="transparent")
            txt.pack(side="left", fill="x", expand=True)
            ctk.CTkLabel(txt, text=preset.name,
                         text_color=self.accent.main if active else T.TEXT,
                         font=T.f(12, "bold"), anchor="w").pack(anchor="w")
            ctk.CTkLabel(txt, text=f"\u03b3{preset.gamma:.2f} · {int(preset.temperature)}K",
                         text_color=T.MUTED, font=T.f(9), anchor="w").pack(anchor="w")
            for widget in (card, inner, txt):
                widget.bind("<Button-1>", lambda e, p=preset: self.apply_profile(p))
            for child in inner.winfo_children() + txt.winfo_children():
                child.bind("<Button-1>", lambda e, p=preset: self.apply_profile(p))
        for c in range(cols):
            self._preset_frame.grid_columnconfigure(c, weight=1)

    def _active_preset_sig(self):
        return tuple(
            (abs(p.gamma - self.cur_gamma) < 0.02 and
             abs(p.brightness - self.cur_brightness) < 0.02 and
             abs(p.temperature - self.cur_temp) < 60)
            for p in DEFAULT_PRESETS
        )

    def _refresh_readouts(self):
        try:
            for key, value in (("brightness", self.cur_brightness),
                               ("temperature", self.cur_temp)):
                sl, pill, fmt = self._slider_widgets[key]
                if pill is not None:
                    pill.configure(text=fmt(value))
            self._preview_panel.update_values(self.cur_gamma, self.cur_brightness, self.cur_temp)
            sig = self._active_preset_sig()
            if sig != getattr(self, "_preset_sig", None):
                self._preset_sig = sig
                self._render_presets()
        except Exception:
            pass

    # ════════════════════════════════════════════════════════════════════
    # Display page (vibrance + resolution)
    # ════════════════════════════════════════════════════════════════════
    def _build_display(self, parent):
        wrap = ctk.CTkScrollableFrame(parent, fg_color="transparent",
                                      scrollbar_button_color=T.BORDER,
                                      scrollbar_button_hover_color=T.BORDER2)
        wrap.pack(fill="both", expand=True, padx=14, pady=(0, 4))

        # ── Digital vibrance ─────────────────────────────────────────────
        vib = ctk.CTkFrame(wrap, fg_color=T.SURF2, corner_radius=16)
        vib.pack(fill="x", pady=(8, 12))
        head = ctk.CTkFrame(vib, fg_color="transparent")
        head.pack(fill="x", padx=16, pady=(14, 0))
        ctk.CTkLabel(head, text="DIGITAL VIBRANCE", text_color=T.MUTED2,
                     font=T.f(9)).pack(side="left")
        self._vib_pill = ctk.CTkLabel(head, text=f"{self.cur_vibrance}%",
                                      text_color=self.accent.main, fg_color=T.SURF3,
                                      corner_radius=8, font=T.f(12, "bold"),
                                      width=58, height=22)
        self._vib_pill.pack(side="right")

        if self.vibrance.available():
            self._vib_slider = GlowSlider(
                vib, width=360, height=42, lo=0, hi=100, value=self.cur_vibrance,
                kind="vibrance", bg=T.SURF2, accent=self.accent.main,
                accent_bright=self.accent.bright, on_change=self._on_vibrance)
            self._vib_slider.pack(fill="x", padx=16, pady=(6, 4))
            rng = ctk.CTkFrame(vib, fg_color="transparent")
            rng.pack(fill="x", padx=18, pady=(0, 6))
            ctk.CTkLabel(rng, text="0  grayscale", text_color=T.MUTED2,
                         font=T.f(9)).pack(side="left")
            ctk.CTkLabel(rng, text="50  neutral", text_color=T.MUTED2,
                         font=T.f(9)).pack(side="left", expand=True)
            ctk.CTkLabel(rng, text="100  max", text_color=T.MUTED2,
                         font=T.f(9)).pack(side="right")
            ctk.CTkLabel(vib, text=f"via {self.vibrance.name}", text_color=T.MUTED2,
                         font=T.f(9), anchor="w").pack(anchor="w", padx=16, pady=(0, 14))
        else:
            ctk.CTkLabel(
                vib, text="Digital vibrance isn't available on this GPU/driver.\n"
                          "(Requires NVIDIA on Windows, or nvidia-settings on Linux.)",
                text_color=T.MUTED, font=T.f(11), justify="left",
            ).pack(anchor="w", padx=16, pady=(8, 16))

        # ── Resolution ───────────────────────────────────────────────────
        res = ctk.CTkFrame(wrap, fg_color=T.SURF2, corner_radius=16)
        res.pack(fill="x", pady=(0, 12))
        ctk.CTkLabel(res, text="RESOLUTION & REFRESH RATE", text_color=T.MUTED2,
                     font=T.f(9), anchor="w").pack(anchor="w", padx=16, pady=(14, 2))
        cur = resmod.current_mode(self._primary.id)
        ctk.CTkLabel(res, text=f"Current: {cur.label if cur else 'unknown'}",
                     text_color=T.MUTED, font=T.f(10), anchor="w").pack(anchor="w", padx=16, pady=(0, 8))

        self._res_modes = resmod.list_modes(self._primary.id)
        labels = [m.label for m in self._res_modes] or ["No modes found"]
        self._res_combo = ctk.CTkOptionMenu(
            res, values=labels, fg_color=T.SURF3, button_color=T.SURF3,
            button_hover_color=T.BORDER2, text_color=T.TEXT, dropdown_fg_color=T.SURF3,
            dropdown_hover_color=T.SURF2, dropdown_text_color=T.TEXT,
            corner_radius=8, font=T.f(11), dynamic_resizing=False)
        if cur:
            match = next((m for m in self._res_modes if m.width == cur.width and
                          m.height == cur.height and m.freq == cur.freq and m.scaling == cur.scaling), None)
            if match:
                self._res_combo.set(match.label)
        self._res_combo.pack(fill="x", padx=16, pady=(0, 10))

        btns = ctk.CTkFrame(res, fg_color="transparent")
        btns.pack(fill="x", padx=16, pady=(0, 14))
        ctk.CTkButton(btns, text="Apply", height=34, fg_color=self.accent.dim,
                      hover_color=T.SURF3, text_color=self.accent.main, corner_radius=10,
                      font=T.f(12, "bold"), command=self._apply_resolution).pack(
                          side="left", fill="x", expand=True, padx=(0, 6))
        ctk.CTkButton(btns, text="Restore", height=34, fg_color=T.SURF3,
                      hover_color=T.BORDER2, text_color=T.MUTED, corner_radius=10,
                      font=T.f(12), command=self._restore_resolution).pack(
                          side="left", fill="x", expand=True, padx=(6, 0))
        if not self._res_modes:
            ctk.CTkLabel(res, text="Resolution switching isn't supported here yet.",
                         text_color=T.MUTED, font=T.f(10)).pack(anchor="w", padx=16, pady=(0, 12))

    def _on_vibrance(self, v):
        self.cur_vibrance = int(round(v))
        self._vib_pill.configure(text=f"{self.cur_vibrance}%")
        if self.vibrance.available():
            self.vibrance.set_percent(self.cur_vibrance)
        self.settings.vibrance = self.cur_vibrance
        save_settings(self.settings)

    def _selected_res_mode(self):
        label = self._res_combo.get()
        return next((m for m in self._res_modes if m.label == label), None)

    def _apply_resolution(self):
        mode = self._selected_res_mode()
        if not mode:
            return
        prev = resmod.current_mode(self._primary.id)
        ok, msg = resmod.apply_mode(self._primary.id, mode)
        if ok:
            self._status(f"Applied {mode.label}")
            self._confirm_resolution(prev)
        else:
            self._status(f"Resolution failed: {msg}", error=True)

    def _restore_resolution(self):
        if resmod.restore(self._primary.id):
            self._status("Resolution restored")
        else:
            self._status("Couldn't restore resolution", warn=True)

    def _confirm_resolution(self, prev_mode, seconds=12):
        """Auto-revert dialog so a bad mode can't lock the user out."""
        if self._res_revert_job:
            try:
                self.root.after_cancel(self._res_revert_job)
            except Exception:
                pass
        top = ctk.CTkToplevel(self.root, fg_color=T.SURF)
        top.title("Keep display mode?")
        top.geometry("320x150")
        top.attributes("-topmost", True)
        top.resizable(False, False)
        try:
            top.grab_set()
        except Exception:
            pass
        lbl = ctk.CTkLabel(top, text="", text_color=T.TEXT, font=T.f(12), justify="center")
        lbl.pack(pady=(22, 14), padx=16)
        row = ctk.CTkFrame(top, fg_color="transparent")
        row.pack(pady=(0, 16))
        state = {"left": seconds, "job": None}

        def keep():
            if state["job"]:
                self.root.after_cancel(state["job"])
            self._res_revert_job = None
            top.destroy()
            self._status("Display mode kept")

        def revert():
            if state["job"]:
                self.root.after_cancel(state["job"])
            self._res_revert_job = None
            if prev_mode:
                resmod.apply_mode(self._primary.id, prev_mode)
            else:
                resmod.restore(self._primary.id)
            top.destroy()
            self._status("Reverted display mode")

        def tick():
            lbl.configure(text=f"Keep this display mode?\nReverting in {state['left']}s")
            if state["left"] <= 0:
                revert()
                return
            state["left"] -= 1
            state["job"] = self.root.after(1000, tick)

        ctk.CTkButton(row, text="Keep", width=110, height=34, fg_color=self.accent.dim,
                      hover_color=T.SURF3, text_color=self.accent.main, corner_radius=10,
                      font=T.f(12, "bold"), command=keep).pack(side="left", padx=6)
        ctk.CTkButton(row, text="Revert", width=110, height=34, fg_color=T.SURF3,
                      hover_color=T.BORDER2, text_color=T.MUTED, corner_radius=10,
                      font=T.f(12), command=revert).pack(side="left", padx=6)
        tick()

    # ════════════════════════════════════════════════════════════════════
    # Games page (per-app automation)
    # ════════════════════════════════════════════════════════════════════
    def _build_games(self, parent):
        wrap = ctk.CTkFrame(parent, fg_color="transparent")
        wrap.pack(fill="both", expand=True, padx=18, pady=(0, 8))

        card = ctk.CTkFrame(wrap, fg_color=T.SURF2, corner_radius=16)
        card.pack(fill="x", pady=(8, 10))
        ctk.CTkLabel(card, text="NEW GAME PROFILE", text_color=T.MUTED2,
                     font=T.f(9), anchor="w").pack(anchor="w", padx=16, pady=(12, 8))
        ctk.CTkLabel(card, text="Apply a vibrance level automatically while a program is running.",
                     text_color=T.MUTED, font=T.f(10), anchor="w").pack(anchor="w", padx=16, pady=(0, 8))

        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=(0, 6))
        self._game_proc = ctk.CTkEntry(
            row, height=34, placeholder_text="process e.g. game.exe", fg_color=T.SURF3,
            text_color=T.TEXT, border_color=T.BORDER2, border_width=1, corner_radius=8,
            font=T.f(12))
        self._game_proc.pack(side="left", fill="x", expand=True, padx=(0, 10))
        ctk.CTkLabel(row, text="vibrance", text_color=T.MUTED, font=T.f(11)).pack(side="left", padx=(0, 6))
        self._game_vib = ctk.CTkEntry(row, width=56, height=34, fg_color=T.SURF3,
                                      text_color=T.TEXT, border_color=T.BORDER2, border_width=1,
                                      corner_radius=8, justify="center", font=T.f(12))
        self._game_vib.insert(0, "100")
        self._game_vib.pack(side="left")
        ctk.CTkLabel(row, text="%", text_color=T.MUTED, font=T.f(11)).pack(side="left", padx=(3, 0))

        row2 = ctk.CTkFrame(card, fg_color="transparent")
        row2.pack(fill="x", padx=16, pady=(0, 6))
        self.v_game_res = tk.BooleanVar(value=False)
        ctk.CTkSwitch(row2, text="Also switch resolution to", variable=self.v_game_res,
                      progress_color=self.accent.main, button_color=T.WHITE,
                      fg_color=T.SURF3, font=T.f(11), width=40).pack(side="left")
        labels = [m.label for m in getattr(self, "_res_modes", resmod.list_modes(self._primary.id))] or ["—"]
        if not hasattr(self, "_res_modes"):
            self._res_modes = resmod.list_modes(self._primary.id)
        self._game_res_combo = ctk.CTkOptionMenu(
            row2, values=labels, fg_color=T.SURF3, button_color=T.SURF3,
            button_hover_color=T.BORDER2, text_color=T.TEXT, dropdown_fg_color=T.SURF3,
            dropdown_hover_color=T.SURF2, dropdown_text_color=T.TEXT, corner_radius=8,
            font=T.f(10), dynamic_resizing=False, width=220)
        self._game_res_combo.pack(side="left", padx=(10, 0))

        ctk.CTkButton(card, text="+  Add profile", height=36, fg_color=T.SURF3,
                      hover_color=T.BORDER2, text_color=self.accent.main, corner_radius=10,
                      font=T.f(12, "bold"), command=self._add_game_rule).pack(
                          fill="x", padx=16, pady=(2, 14))

        ctk.CTkLabel(wrap, text="GAME PROFILES", text_color=T.MUTED2, font=T.f(9),
                     anchor="w").pack(anchor="w", padx=6, pady=(6, 4))
        self._game_list = ctk.CTkScrollableFrame(
            wrap, fg_color="transparent", scrollbar_button_color=T.BORDER,
            scrollbar_button_hover_color=T.BORDER2)
        self._game_list.pack(fill="both", expand=True, pady=(0, 6))
        self._render_game_rules()

    def _add_game_rule(self):
        proc = normalize_name(self._game_proc.get())
        if not proc:
            self._status("Enter a process name", warn=True)
            return
        try:
            vib = max(0, min(100, int(self._game_vib.get())))
        except ValueError:
            self._status("Vibrance must be 0-100", error=True)
            return
        rule = GameRule(process=proc, vibrance=vib)
        if self.v_game_res.get():
            mode = next((m for m in self._res_modes if m.label == self._game_res_combo.get()), None)
            if mode:
                rule.change_resolution = True
                rule.width, rule.height, rule.freq = mode.width, mode.height, mode.freq
                rule.bpp, rule.scaling = mode.bpp, mode.scaling
        # replace existing rule for same process
        self.settings.game_rules = [r for r in self.settings.game_rules if r.process != proc]
        self.settings.game_rules.append(rule)
        save_settings(self.settings)
        self._game_proc.delete(0, "end")
        self._render_game_rules()
        self._refresh_watcher()
        self._status(f"Added profile for {proc}")

    def _delete_game_rule(self, rule):
        self.settings.game_rules = [r for r in self.settings.game_rules if r is not rule]
        save_settings(self.settings)
        self._render_game_rules()
        self._refresh_watcher()
        self._status(f"Removed {rule.process}")

    def _render_game_rules(self):
        for w in self._game_list.winfo_children():
            w.destroy()
        if not self.settings.game_rules:
            ctk.CTkLabel(self._game_list, text="No game profiles yet.\nAdd one above.",
                         text_color=T.MUTED2, font=T.f(12), justify="center").pack(pady=40)
            return
        for rule in self.settings.game_rules:
            r = ctk.CTkFrame(self._game_list, fg_color=T.SURF2, corner_radius=10)
            r.pack(fill="x", pady=3)
            left = ctk.CTkFrame(r, fg_color="transparent")
            left.pack(side="left", fill="x", expand=True, padx=14, pady=10)
            ctk.CTkLabel(left, text=f"\u25B6  {rule.process}", text_color=T.TEXT,
                         font=T.f(12, "bold"), anchor="w").pack(anchor="w")
            detail = f"vibrance {rule.vibrance}%"
            if rule.change_resolution and rule.width:
                detail += f"  ·  {rule.width}x{rule.height}@{rule.freq}"
            ctk.CTkLabel(left, text=detail, text_color=T.MUTED, font=T.f(10),
                         anchor="w").pack(anchor="w")
            ctk.CTkButton(r, text="\u2715", width=28, height=28, fg_color="transparent",
                          hover_color=self.accent.danger_bg, text_color=T.DANGER,
                          corner_radius=6, font=T.f(12),
                          command=lambda x=rule: self._delete_game_rule(x)).pack(side="right", padx=10, pady=10)

    def _refresh_watcher(self):
        self._watcher.set_targets({r.process for r in self.settings.game_rules})

    def _rule_for(self, proc):
        return next((r for r in self.settings.game_rules if r.process == proc), None)

    def _on_app_start(self, proc):
        rule = self._rule_for(proc)
        if not rule:
            return
        if self.vibrance.available():
            self._rule_saved_vibrance = self.cur_vibrance
            self.vibrance.set_percent(rule.vibrance)
        if rule.change_resolution and rule.width:
            self._rule_saved_mode = resmod.current_mode(self._primary.id)
            resmod.apply_mode(self._primary.id, resmod.DisplayMode(
                rule.width, rule.height, rule.freq, rule.bpp, rule.scaling))
        self.root.after(0, lambda: self._status(f"{proc} detected \u2192 vibrance {rule.vibrance}%"))

    def _on_app_stop(self, proc):
        rule = self._rule_for(proc)
        if not rule:
            return
        if self.vibrance.available() and self._rule_saved_vibrance is not None:
            self.vibrance.set_percent(self._rule_saved_vibrance)
            self._rule_saved_vibrance = None
        if rule.change_resolution and self._rule_saved_mode:
            resmod.apply_mode(self._primary.id, self._rule_saved_mode)
            self._rule_saved_mode = None
        self.root.after(0, lambda: self._status(f"{proc} closed \u2192 vibrance restored"))

    # ════════════════════════════════════════════════════════════════════
    # Hotkeys page
    # ════════════════════════════════════════════════════════════════════
    def _build_hotkeys(self, parent):
        wrap = ctk.CTkFrame(parent, fg_color="transparent")
        wrap.pack(fill="both", expand=True, padx=18, pady=(0, 8))

        if not hotkeys_available():
            ctk.CTkLabel(
                wrap,
                text="Global hotkeys aren't available on this system.\n"
                     "(On Linux run with sufficient permissions; on macOS this is restricted.)",
                text_color=T.MUTED, font=T.f(12), justify="center",
            ).pack(pady=60)
            return

        card = ctk.CTkFrame(wrap, fg_color=T.SURF2, corner_radius=14)
        card.pack(fill="x", pady=(8, 10))
        ctk.CTkLabel(card, text="NEW BINDING", text_color=T.MUTED2, font=T.f(9),
                     anchor="w").pack(anchor="w", padx=16, pady=(12, 8))

        values = ["Keyboard", "Mouse"] if mouse_available() else ["Keyboard"]
        self._bind_seg = ctk.CTkSegmentedButton(
            card, values=values, variable=self.v_bind_type,
            selected_color=self.accent.dim, selected_hover_color=T.SURF3,
            unselected_color=T.SURF3, unselected_hover_color=T.SURF2,
            text_color=T.TEXT, corner_radius=8, font=T.f(12))
        self._bind_seg.pack(fill="x", padx=16, pady=(0, 10))

        # mini gamma/brightness/temp inputs for the binding
        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=(0, 8))
        self.bind_g = self._mini_entry(row, "\u03b3", f"{self.cur_gamma:.2f}")
        self.bind_b = self._mini_entry(row, "\u2600", f"{int(self.cur_brightness*100)}")
        self.bind_t = self._mini_entry(row, "K", f"{self.cur_temp}")

        self._record_btn = ctk.CTkButton(
            card, text="\u23FA  Record Hotkey", height=38, fg_color=T.SURF3,
            hover_color=T.BORDER2, text_color=T.MUTED, corner_radius=10,
            font=T.f(12, "bold"), command=self._start_record)
        self._record_btn.pack(fill="x", padx=16, pady=(0, 14))

        ctk.CTkLabel(wrap, text="ACTIVE BINDINGS", text_color=T.MUTED2, font=T.f(9),
                     anchor="w").pack(anchor="w", padx=6, pady=(6, 4))
        self._bind_list = ctk.CTkScrollableFrame(
            wrap, fg_color="transparent", scrollbar_button_color=T.BORDER,
            scrollbar_button_hover_color=T.BORDER2)
        self._bind_list.pack(fill="both", expand=True, pady=(0, 6))

    def _mini_entry(self, parent, glyph, value):
        grp = ctk.CTkFrame(parent, fg_color="transparent")
        grp.pack(side="left", padx=(0, 14))
        ctk.CTkLabel(grp, text=glyph, text_color=T.MUTED, font=T.f(12)).pack(side="left", padx=(0, 4))
        var = tk.StringVar(value=value)
        ctk.CTkEntry(grp, width=56, height=30, textvariable=var, fg_color=T.SURF3,
                     text_color=T.TEXT, border_color=T.BORDER2, border_width=1,
                     corner_radius=6, justify="center", font=T.f(12)).pack(side="left")
        return var

    # ════════════════════════════════════════════════════════════════════
    # Schedule page
    # ════════════════════════════════════════════════════════════════════
    def _build_schedule(self, parent):
        wrap = ctk.CTkFrame(parent, fg_color="transparent")
        wrap.pack(fill="both", expand=True, padx=18, pady=(0, 8))

        head = ctk.CTkFrame(wrap, fg_color=T.SURF2, corner_radius=14)
        head.pack(fill="x", pady=(8, 10))
        left = ctk.CTkFrame(head, fg_color="transparent")
        left.pack(side="left", padx=16, pady=14, fill="x", expand=True)
        ctk.CTkLabel(left, text="Automatic day / night", text_color=T.TEXT,
                     font=T.f(13)).pack(anchor="w")
        ctk.CTkLabel(left, text="Switch profiles automatically at set times",
                     text_color=T.MUTED, font=T.f(10)).pack(anchor="w")
        ctk.CTkSwitch(head, text="", variable=self.v_sched, command=self._on_schedule_toggle,
                      progress_color=self.accent.main, button_color=T.WHITE,
                      fg_color=T.SURF3, width=46).pack(side="right", padx=16)

        preset_names = [p.name for p in DEFAULT_PRESETS]
        self.v_sched_day = ctk.StringVar(value=self.settings.schedule_day)
        self.v_sched_night = ctk.StringVar(value=self.settings.schedule_night)
        self.v_day_time = tk.StringVar(value=self.settings.schedule_day_time)
        self.v_night_time = tk.StringVar(value=self.settings.schedule_night_time)

        self._sched_card("\u2600  Day", self.v_sched_day, self.v_day_time, preset_names, wrap)
        self._sched_card("\u263E  Night", self.v_sched_night, self.v_night_time, preset_names, wrap)

    def _sched_card(self, title, profile_var, time_var, names, parent):
        card = ctk.CTkFrame(parent, fg_color=T.SURF2, corner_radius=14)
        card.pack(fill="x", pady=6)
        ctk.CTkLabel(card, text=title, text_color=T.TEXT, font=T.f(13),
                     anchor="w").pack(anchor="w", padx=16, pady=(12, 6))
        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=(0, 14))
        ctk.CTkOptionMenu(row, values=names, variable=profile_var, fg_color=T.SURF3,
                          button_color=T.SURF3, button_hover_color=T.BORDER2,
                          text_color=T.TEXT, dropdown_fg_color=T.SURF3,
                          dropdown_hover_color=T.SURF2, dropdown_text_color=T.TEXT,
                          corner_radius=8, font=T.f(12),
                          command=lambda _v: self._save_schedule()).pack(side="left")
        ctk.CTkLabel(row, text="at", text_color=T.MUTED, font=T.f(11)).pack(side="left", padx=10)
        e = ctk.CTkEntry(row, width=80, height=32, textvariable=time_var, fg_color=T.SURF3,
                         text_color=T.TEXT, border_color=T.BORDER2, border_width=1,
                         corner_radius=8, justify="center", font=T.f(12))
        e.pack(side="left")
        e.bind("<FocusOut>", lambda _e: self._save_schedule())
        e.bind("<Return>", lambda _e: self._save_schedule())
        ctk.CTkLabel(row, text="HH:MM", text_color=T.MUTED2, font=T.f(10)).pack(side="left", padx=8)

    # ════════════════════════════════════════════════════════════════════
    # Settings page
    # ════════════════════════════════════════════════════════════════════
    def _build_settings(self, parent):
        wrap = ctk.CTkScrollableFrame(parent, fg_color="transparent",
                                      scrollbar_button_color=T.BORDER,
                                      scrollbar_button_hover_color=T.BORDER2)
        wrap.pack(fill="both", expand=True, padx=14, pady=(0, 6))

        opts = [
            ("Apply to all monitors", self.v_apply_all,
             "Set values on every connected display at once", self._on_option),
            ("Launch at system startup", self.v_autostart,
             "Start Lumen automatically when you log in", self._on_autostart),
            ("Restore on exit", self.v_restore,
             "Reset displays to neutral when Lumen closes", self._on_option),
            ("Keep window on top", self.v_on_top,
             "Float the window above other apps", self._on_option),
            ("Start minimized to tray", self.v_min,
             "Launch silently into the system tray", self._on_option),
            ("Smooth transitions", self.v_smooth,
             "Animate changes instead of snapping instantly", self._on_option),
        ]
        for i, (label, var, tip, cb) in enumerate(opts):
            card = ctk.CTkFrame(wrap, fg_color=T.SURF2, corner_radius=12)
            card.pack(fill="x", pady=(8 if i == 0 else 5, 0))
            left = ctk.CTkFrame(card, fg_color="transparent")
            left.pack(side="left", padx=16, pady=12, fill="x", expand=True)
            ctk.CTkLabel(left, text=label, text_color=T.TEXT, font=T.f(13),
                         anchor="w").pack(anchor="w")
            ctk.CTkLabel(left, text=tip, text_color=T.MUTED, font=T.f(10),
                         anchor="w").pack(anchor="w")
            ctk.CTkSwitch(card, text="", variable=var, command=cb,
                          progress_color=self.accent.main, button_color=T.WHITE,
                          fg_color=T.SURF3, width=46).pack(side="right", padx=16)

        # Accent picker
        accent_card = ctk.CTkFrame(wrap, fg_color=T.SURF2, corner_radius=12)
        accent_card.pack(fill="x", pady=(12, 0))
        ctk.CTkLabel(accent_card, text="Accent color", text_color=T.TEXT, font=T.f(13),
                     anchor="w").pack(anchor="w", padx=16, pady=(12, 8))
        swatches = ctk.CTkFrame(accent_card, fg_color="transparent")
        swatches.pack(fill="x", padx=16, pady=(0, 14))
        for name, data in T.ACCENTS.items():
            sel = name == self.accent.name
            ctk.CTkButton(
                swatches, text="\u2713" if sel else "", width=42, height=34,
                fg_color=data["main"], hover_color=data["bright"],
                text_color="#000000", corner_radius=10, font=T.f(13, "bold"),
                command=lambda n=name: self._set_accent(n),
            ).pack(side="left", padx=4)

        about = ctk.CTkFrame(wrap, fg_color="transparent")
        about.pack(fill="x", pady=(14, 4))
        ctk.CTkLabel(about, text=f"Lumen v{__version__}  ·  Engine: {self.backend.name}",
                     text_color=T.MUTED2, font=T.f(10)).pack(anchor="w", padx=4)

    # ════════════════════════════════════════════════════════════════════
    # Gamma application
    # ════════════════════════════════════════════════════════════════════
    def _target_monitors(self):
        if self.v_apply_all.get():
            return self.monitors
        label = self.monitor_combo.get()
        for m in self.monitors:
            if m.label == label:
                return [m]
        return self.monitors[:1]

    def _push(self, gamma, brightness, temp) -> tuple[int, int]:
        ramp = GammaRamp.build(gamma, brightness, temp)
        targets = self._target_monitors()
        ok = sum(1 for m in targets if self.backend.set_ramp(m, ramp))
        return ok, len(targets)

    def apply_profile(self, profile: Profile, animate=None, save=True, announce=True):
        profile = profile.normalized()
        if animate is None:
            animate = self.v_smooth.get()

        start = (self.cur_gamma, self.cur_brightness, self.cur_temp)
        end = (profile.gamma, profile.brightness, profile.temperature)
        self._anim_token += 1
        token = self._anim_token

        if animate and start != end:
            threading.Thread(target=self._animate, args=(start, end, token),
                             daemon=True).start()
        else:
            self._push(*end)

        self.cur_gamma, self.cur_brightness, self.cur_temp = end
        self._sync_sliders()
        if announce:
            self._status(f"{profile.name}  ·  \u03b3{end[0]:.2f}  {int(end[1]*100)}%  {int(end[2])}K")
        if save:
            self._save()

    def _animate(self, start, end, token):
        steps = 14
        for s in range(1, steps + 1):
            if token != self._anim_token or self._quitting:
                return
            t = s / steps
            g = start[0] + (end[0] - start[0]) * t
            b = start[1] + (end[1] - start[1]) * t
            k = start[2] + (end[2] - start[2]) * t
            self._push(g, b, k)
            time.sleep(0.012)

    def _sync_sliders(self):
        self._programmatic = True
        try:
            self._dial.set_value(self.cur_gamma)
            self._slider_widgets["brightness"][0].set_value(self.cur_brightness)
            self._slider_widgets["temperature"][0].set_value(self.cur_temp)
            self._refresh_readouts()
        except Exception:
            pass
        self._programmatic = False

    def _on_gamma(self, v):
        if self._programmatic:
            return
        self.cur_gamma = clamp_gamma(v)
        self._live_apply()

    def _on_brightness(self, v):
        if self._programmatic:
            return
        self.cur_brightness = clamp_brightness(v)
        self._live_apply()

    def _on_temp(self, v):
        if self._programmatic:
            return
        self.cur_temp = clamp_temperature(v)
        self._live_apply()

    def _live_apply(self):
        self._anim_token += 1  # cancel any running animation
        self._push(self.cur_gamma, self.cur_brightness, self.cur_temp)
        self._refresh_readouts()
        self._save()

    def _reset_one(self, key):
        if key == "gamma":
            self.cur_gamma = 1.0
        elif key == "brightness":
            self.cur_brightness = 1.0
        else:
            self.cur_temp = TEMP_DEFAULT
        self._live_apply()
        self._sync_sliders()

    def _reset_all(self):
        self.apply_profile(Profile("Neutral", 1.0, 1.0, TEMP_DEFAULT))

    # ════════════════════════════════════════════════════════════════════
    # Hotkey recording / binding
    # ════════════════════════════════════════════════════════════════════
    def _start_record(self):
        if self._recording:
            self._finish_record("esc")
            return
        self._recording = True
        self._record_ts = time.monotonic()
        self._record_btn.configure(text="\u25A0  Press / click…  (Esc cancels)",
                                   fg_color=self.accent.danger_bg, text_color=T.DANGER)
        if self.v_bind_type.get() == "Mouse" and mouse_available():
            self._status("Click any mouse button…")
            self._record_mouse()
        else:
            self._status("Press your keyboard shortcut…")
            threading.Thread(target=self._record_kb, daemon=True).start()

    def _record_mouse(self):
        def got(btn):
            if btn == "left" and (time.monotonic() - self._record_ts) < 0.3:
                self._mouse.set_oneshot(got)
                return
            self.root.after(0, lambda: self._finish_record(f"mouse:{btn}"))
        self._mouse.set_oneshot(got)
        self._kb.hook_escape(lambda e: self.root.after(
            0, lambda: (self._mouse.cancel_oneshot(), self._finish_record("esc"))))

    def _record_kb(self):
        combo = self._kb.read_combo()
        self.root.after(0, lambda: self._finish_record(combo))

    def _finish_record(self, hotkey):
        self._kb.unhook_escape()
        self._mouse.cancel_oneshot()
        self._recording = False
        self._record_btn.configure(text="\u23FA  Record Hotkey", fg_color=T.SURF3,
                                   text_color=T.MUTED)
        hotkey = str(hotkey).strip()
        if not hotkey or hotkey.lower() in ("esc", "escape"):
            self._status("Recording cancelled")
            return
        self._add_binding(hotkey)

    def _add_binding(self, hotkey):
        try:
            gamma = clamp_gamma(float(self.bind_g.get()))
            bright = clamp_brightness(float(self.bind_b.get()) / 100.0)
            temp = clamp_temperature(float(self.bind_t.get()))
        except Exception:
            self._status("Invalid binding values", error=True)
            return
        existing = next((b for b in self.settings.bindings
                         if b.hotkey.lower() == hotkey.lower()), None)
        if existing:
            existing.gamma, existing.brightness, existing.temperature = gamma, bright, temp
        else:
            self.settings.bindings.append(Binding(hotkey, gamma, bright, temp))
        self._save()
        self._render_bindings()
        self._rebind_all()
        self._status(f"Bound  {format_hotkey(hotkey)}")

    def _delete_binding(self, binding):
        if binding in self.settings.bindings:
            self.settings.bindings.remove(binding)
            self._save()
            self._render_bindings()
            self._rebind_all()
            self._status(f"Removed  {format_hotkey(binding.hotkey)}")

    def _render_bindings(self):
        if not hasattr(self, "_bind_list"):
            return
        for w in self._bind_list.winfo_children():
            w.destroy()
        if not self.settings.bindings:
            ctk.CTkLabel(self._bind_list, text="No bindings yet.\nRecord a hotkey above.",
                         text_color=T.MUTED2, font=T.f(12), justify="center").pack(pady=40)
            return
        for b in self.settings.bindings:
            row = ctk.CTkFrame(self._bind_list, fg_color=T.SURF2, corner_radius=10)
            row.pack(fill="x", pady=3)
            is_mouse = b.hotkey.startswith("mouse:")
            icon = "\U0001F5B1" if is_mouse else "\u2328"
            ctk.CTkLabel(row, text=f"{icon}  {format_hotkey(b.hotkey)}",
                         text_color=self.accent.main, fg_color=self.accent.dim,
                         corner_radius=6, font=T.f(11), width=150, anchor="w",
                         padx=10, pady=3).pack(side="left", padx=(10, 8), pady=10)
            ctk.CTkLabel(row, text=f"\u03b3{b.gamma:.2f}  {int(b.brightness*100)}%  {int(b.temperature)}K",
                         text_color=T.MUTED, font=T.f(11)).pack(side="left")
            ctk.CTkButton(row, text="\u2715", width=28, height=28, fg_color="transparent",
                          hover_color=self.accent.danger_bg, text_color=T.DANGER,
                          corner_radius=6, font=T.f(12),
                          command=lambda x=b: self._delete_binding(x)).pack(side="right", padx=10, pady=10)

    def _rebind_all(self):
        self._kb.clear()
        self._mouse.clear_binds()
        for b in self.settings.bindings:
            profile = b.profile()
            if b.hotkey.startswith("mouse:"):
                btn = b.hotkey[6:]
                self._mouse.set_bind(btn, self._make_cb(profile))
            else:
                if not self._kb.add(b.hotkey, self._make_cb(profile)):
                    self._status(f"Can't bind '{b.hotkey}'", warn=True)

    def _make_cb(self, profile):
        return lambda: self.root.after(0, lambda: self._toggle(profile))

    def _toggle(self, profile: Profile):
        now = time.monotonic()
        if now - self._last_toggle < 0.05:
            return
        self._last_toggle = now
        same = (abs(self.cur_gamma - profile.gamma) < 0.02 and
                abs(self.cur_brightness - profile.brightness) < 0.02 and
                abs(self.cur_temp - profile.temperature) < 60)
        if same:
            self.apply_profile(Profile("Neutral", 1.0, 1.0, TEMP_DEFAULT))
        else:
            self.apply_profile(profile)

    # ════════════════════════════════════════════════════════════════════
    # Schedule logic
    # ════════════════════════════════════════════════════════════════════
    def _profile_by_name(self, name) -> Profile:
        for p in DEFAULT_PRESETS:
            if p.name == name:
                return p
        return Profile("Normal", 1.0, 1.0, TEMP_DEFAULT)

    def _on_schedule_toggle(self):
        self._save_schedule()
        if self.v_sched.get():
            self._apply_scheduled(force=True)

    def _save_schedule(self):
        self.settings.schedule_enabled = self.v_sched.get()
        self.settings.schedule_day = self.v_sched_day.get()
        self.settings.schedule_night = self.v_sched_night.get()
        self.settings.schedule_day_time = self.v_day_time.get().strip()
        self.settings.schedule_night_time = self.v_night_time.get().strip()
        save_settings(self.settings)

    @staticmethod
    def _parse_time(text) -> int | None:
        try:
            h, m = text.split(":")
            return int(h) * 60 + int(m)
        except Exception:
            return None

    def _is_day(self) -> bool:
        from datetime import datetime
        day = self._parse_time(self.settings.schedule_day_time)
        night = self._parse_time(self.settings.schedule_night_time)
        if day is None or night is None:
            return True
        now = datetime.now().hour * 60 + datetime.now().minute
        if day < night:
            return day <= now < night
        return now >= day or now < night

    def _apply_scheduled(self, force=False):
        if not self.settings.schedule_enabled:
            return
        target = (self.settings.schedule_day if self._is_day()
                  else self.settings.schedule_night)
        if force or getattr(self, "_last_sched", None) != target:
            self._last_sched = target
            self.apply_profile(self._profile_by_name(target))

    def _start_scheduler(self):
        def tick():
            if self._quitting:
                return
            try:
                self._apply_scheduled()
            except Exception:
                pass
            self._sched_after = self.root.after(30000, tick)
        if self.settings.schedule_enabled:
            self._apply_scheduled(force=True)
        self._sched_after = self.root.after(30000, tick)

    # ════════════════════════════════════════════════════════════════════
    # Settings handlers
    # ════════════════════════════════════════════════════════════════════
    def _on_monitor_change(self, _v):
        self._save()
        if not self.v_apply_all.get():
            self._push(self.cur_gamma, self.cur_brightness, self.cur_temp)

    def _on_option(self):
        self.root.attributes("-topmost", self.v_on_top.get())
        self._save()

    def _on_autostart(self):
        want = self.v_autostart.get()
        ok = set_autostart(want)
        if not ok:
            self.v_autostart.set(not want)
            self._status("Couldn't change autostart setting", error=True)
        else:
            self._status("Launch at startup " + ("enabled" if want else "disabled"))
        self._save()

    def _set_accent(self, name):
        self.accent.set(name)
        self.settings.accent = self.accent.name
        save_settings(self.settings)
        self._status(f"Accent set to {name}")
        # live-update custom widgets
        try:
            self._dial.set_accent(self.accent.dim, self.accent.main, self.accent.bright)
            self._slider_widgets["brightness"][0].set_accent(self.accent.main, self.accent.bright)
            self._slider_widgets["temperature"][0].set_accent(self.accent.main, self.accent.bright)
            for key in ("brightness", "temperature"):
                self._slider_widgets[key][1].configure(text_color=self.accent.main)
        except Exception:
            pass
        for n, btn in self.nav_btns.items():
            if n == self._page_title.cget("text"):
                btn.configure(text_color=self.accent.main, fg_color=T.SURF3)
        self._render_presets()
        self._goto(self._page_title.cget("text"))

    def _select_monitor_initial(self):
        saved = self.settings.selected_monitor
        if saved in self.monitor_labels:
            self.monitor_combo.set(saved)
        elif self.monitor_labels:
            self.monitor_combo.set(self.monitor_labels[0])

    def _save(self):
        self.settings.gamma = self.cur_gamma
        self.settings.brightness = self.cur_brightness
        self.settings.temperature = self.cur_temp
        self.settings.selected_monitor = self.monitor_combo.get()
        self.settings.apply_all_monitors = self.v_apply_all.get()
        self.settings.restore_on_exit = self.v_restore.get()
        self.settings.keep_on_top = self.v_on_top.get()
        self.settings.start_minimized = self.v_min.get()
        self.settings.smooth_transitions = self.v_smooth.get()
        self.settings.accent = self.accent.name
        self.settings.autostart = self.v_autostart.get()
        self.settings.vibrance = self.cur_vibrance
        save_settings(self.settings)

    # ════════════════════════════════════════════════════════════════════
    # Tray
    # ════════════════════════════════════════════════════════════════════
    def _tray_image(self):
        try:
            return Image.open(asset("lumen_256.png"))
        except Exception:
            img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
            d = ImageDraw.Draw(img)
            d.ellipse((6, 6, 58, 58), fill=(20, 20, 26), outline=(245, 166, 35), width=3)
            return img

    def _create_tray(self):
        if not _HAS_TRAY:
            return
        items = [pystray.MenuItem("Show Lumen", self._show_window, default=True),
                 pystray.Menu.SEPARATOR]
        for p in DEFAULT_PRESETS:
            items.append(pystray.MenuItem(
                f"{p.name}", (lambda prof: lambda i, it: self.root.after(
                    0, lambda: self.apply_profile(prof)))(p)))
        items += [pystray.Menu.SEPARATOR, pystray.MenuItem("Quit", lambda i, it: self._quit())]
        self._tray = pystray.Icon("Lumen", self._tray_image(), APP_NAME, pystray.Menu(*items))
        threading.Thread(target=self._tray.run, daemon=True).start()

    def hide_to_tray(self):
        if self._quitting:
            return
        if not _HAS_TRAY:
            self.root.iconify()
            return
        self.root.withdraw()
        if self._tray is None:
            self._create_tray()

    def _show_window(self, icon=None, item=None):
        if icon:
            try:
                icon.stop()
            except Exception:
                pass
        self._tray = None
        self.root.after(0, lambda: (self.root.deiconify(), self.root.lift(),
                                    self.root.focus_force()))

    # ════════════════════════════════════════════════════════════════════
    # Status / quit
    # ════════════════════════════════════════════════════════════════════
    def _status(self, msg, error=False, warn=False):
        color = T.DANGER if error else (T.WARN if warn else T.MUTED)
        try:
            self._status_lbl.configure(text=str(msg), text_color=color)
        except Exception:
            pass

    def _quit(self, *_):
        self._quitting = True
        self._anim_token += 1
        self._kb.clear()
        self._mouse.clear_binds()
        try:
            self._watcher.stop()
        except Exception:
            pass
        if self._res_revert_job:
            try:
                self.root.after_cancel(self._res_revert_job)
            except Exception:
                pass
        # if a game rule was active, restore the saved desktop vibrance
        if self.vibrance.available() and self._rule_saved_vibrance is not None:
            self.vibrance.set_percent(self._rule_saved_vibrance)
        self._save()
        if self.v_restore.get():
            for m in self.monitors:
                self.backend.reset(m)
        if self._tray:
            try:
                self._tray.stop()
            except Exception:
                pass
        try:
            self.root.after(0, self.root.destroy)
        except Exception:
            self.root.destroy()

    def run(self):
        self.root.mainloop()
