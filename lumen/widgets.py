"""
Custom, PIL-rendered widgets that give Lumen a modern, premium look that plain
tkinter / customtkinter can't achieve: an antialiased circular gamma dial with
a glowing gradient arc, gradient-filled "glow" sliders (the temperature track
shows real Kelvin colors) and a smooth live preview panel.

Everything is drawn into supersampled RGBA images with Pillow (anti-aliasing +
Gaussian-blur glow) and shown on a tk.Canvas, with crisp native text on top.
"""

from __future__ import annotations

import math
import tkinter as tk

from PIL import Image, ImageDraw, ImageFilter, ImageTk

from .engine import temperature_to_rgb

SS = 2  # supersampling factor for anti-aliasing


def hex_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def lerp(a, b, t):
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


def mix(color, bg, alpha):
    """Flatten an RGBA-ish color onto bg at given alpha (0..1)."""
    return lerp(bg, color, alpha)


class RadialDial(tk.Canvas):
    """A circular gauge with a glowing gradient arc and a draggable handle."""

    def __init__(self, parent, *, size=232, lo=0.30, hi=2.50, value=1.0,
                 bg="#121218", accent_dim="#3A2A0C", accent="#F5A623",
                 accent_bright="#FFC14D", on_change=None, fmt=lambda v: f"{v:.2f}",
                 caption="GAMMA"):
        super().__init__(parent, width=size, height=size, bg=bg,
                         highlightthickness=0, bd=0)
        self.size = size
        self.lo, self.hi = lo, hi
        self.value = value
        self.bg = hex_rgb(bg)
        self.c_dim = hex_rgb(accent_dim)
        self.c_main = hex_rgb(accent)
        self.c_bright = hex_rgb(accent_bright)
        self.on_change = on_change
        self.fmt = fmt
        self.caption = caption

        self._start = 135.0
        self._sweep = 270.0
        self._photo = None

        self.bind("<Button-1>", self._on_drag)
        self.bind("<B1-Motion>", self._on_drag)
        self.redraw()

    # ── geometry ────────────────────────────────────────────────────────
    def _frac(self):
        return (self.value - self.lo) / (self.hi - self.lo)

    def _angle_for(self, frac):
        return self._start + frac * self._sweep

    def set_value(self, v, notify=False):
        v = max(self.lo, min(self.hi, v))
        changed = abs(v - self.value) > 1e-9
        self.value = v
        self.redraw()
        if notify and changed and self.on_change:
            self.on_change(v)

    def set_accent(self, dim, main, bright):
        self.c_dim, self.c_main, self.c_bright = hex_rgb(dim), hex_rgb(main), hex_rgb(bright)
        self.redraw()

    def _on_drag(self, e):
        c = self.size / 2
        ang = math.degrees(math.atan2(e.y - c, e.x - c)) % 360
        # shift into the [start, start+sweep] domain
        rel = (ang - self._start) % 360
        if rel > self._sweep:
            # snap to nearest end across the bottom gap
            rel = 0 if rel - self._sweep > (360 - self._sweep) / 2 else self._sweep
        frac = rel / self._sweep
        self.set_value(self.lo + frac * (self.hi - self.lo), notify=True)

    # ── rendering ───────────────────────────────────────────────────────
    def redraw(self):
        s = self.size * SS
        img = Image.new("RGBA", (s, s), self.bg + (255,))
        glow = Image.new("RGBA", (s, s), (0, 0, 0, 0))
        gd = ImageDraw.Draw(glow)
        d = ImageDraw.Draw(img)

        cx = cy = s / 2
        tw = int(14 * SS)
        r = s / 2 - tw - int(10 * SS)
        box = [cx - r, cy - r, cx + r, cy + r]
        rc = r - tw / 2  # arc centerline (PIL arc width extends inward from box)

        # track
        self._arc(d, box, self._start, self._start + self._sweep, tw,
                  lambda t: mix(self.c_main, self.bg, 0.10))

        # progress (gradient dim -> bright) + glow
        frac = self._frac()
        end = self._start + frac * self._sweep
        if frac > 0.001:
            self._arc(d, box, self._start, end, tw,
                      lambda t: lerp(self.c_dim, self.c_bright, 0.25 + 0.75 * t))
            self._arc(gd, box, self._start, end, tw + int(6 * SS),
                      lambda t: self.c_main)
            # rounded cap centered on the arc at the live end
            ex = cx + rc * math.cos(math.radians(end))
            ey = cy + rc * math.sin(math.radians(end))
            cap = tw * 0.6
            d.ellipse([ex - cap, ey - cap, ex + cap, ey + cap], fill=self.c_bright + (255,))
            gd.ellipse([ex - cap * 1.4, ey - cap * 1.4, ex + cap * 1.4, ey + cap * 1.4],
                       fill=self.c_main + (255,))

        glow = glow.filter(ImageFilter.GaussianBlur(int(9 * SS)))
        out = Image.alpha_composite(img, glow)
        out = Image.alpha_composite(out, img)  # keep crisp arc above glow
        out = out.resize((self.size, self.size), Image.LANCZOS)

        self._photo = ImageTk.PhotoImage(out)
        self.delete("all")
        self.create_image(0, 0, anchor="nw", image=self._photo)

        cxs = self.size / 2
        self.create_text(cxs, cxs - 6, text=self.fmt(self.value),
                         fill="#FFFFFF", font=("Segoe UI", int(self.size * 0.20), "bold"))
        self.create_text(cxs, cxs + self.size * 0.18, text=self.caption,
                         fill="#7A7A88", font=("Segoe UI", 10))

    def _arc(self, draw, box, a0, a1, width, color_fn):
        step = 2.0
        a = a0
        while a < a1:
            b = min(a + step, a1)
            t = (a - a0) / max(0.001, (a1 - a0))
            col = color_fn(t)
            draw.arc(box, a, b + 0.6, fill=col + (255,), width=int(width))
            a = b


class GlowSlider(tk.Canvas):
    """Horizontal slider with a gradient-filled track and a glowing knob.

    kind="brightness" -> dark→accent gradient
    kind="temperature" -> real Kelvin color gradient
    kind="accent"     -> dim→bright accent gradient
    """

    def __init__(self, parent, *, width=300, height=46, lo=0.0, hi=1.0, value=0.5,
                 kind="accent", bg="#121218", accent="#F5A623",
                 accent_bright="#FFC14D", on_change=None):
        super().__init__(parent, width=width, height=height, bg=bg,
                         highlightthickness=0, bd=0)
        self.w, self.h = width, height
        self.lo, self.hi = lo, hi
        self.value = value
        self.kind = kind
        self.bg = hex_rgb(bg)
        self.c_main = hex_rgb(accent)
        self.c_bright = hex_rgb(accent_bright)
        self.on_change = on_change
        self._photo = None
        self.bind("<Button-1>", self._on_drag)
        self.bind("<B1-Motion>", self._on_drag)
        self.bind("<Configure>", self._on_resize)
        self.redraw()

    def _on_resize(self, e):
        if abs(e.width - self.w) > 1:
            self.w = e.width
            self.redraw()

    def set_value(self, v, notify=False):
        v = max(self.lo, min(self.hi, v))
        changed = abs(v - self.value) > 1e-9
        self.value = v
        self.redraw()
        if notify and changed and self.on_change:
            self.on_change(v)

    def set_accent(self, main, bright):
        self.c_main, self.c_bright = hex_rgb(main), hex_rgb(bright)
        self.redraw()

    def _frac(self):
        return (self.value - self.lo) / (self.hi - self.lo)

    def _on_drag(self, e):
        pad = self.h / 2
        frac = (e.x - pad) / max(1, (self.w - 2 * pad))
        frac = max(0.0, min(1.0, frac))
        self.set_value(self.lo + frac * (self.hi - self.lo), notify=True)

    def _track_color(self, t):
        if self.kind == "temperature":
            k = self.lo + t * (self.hi - self.lo)
            rm, gm, bm = temperature_to_rgb(int(k))
            return (int(rm * 255), int(gm * 255), int(bm * 255))
        if self.kind == "brightness":
            return lerp(mix(self.c_main, self.bg, 0.25), self.c_bright, t)
        if self.kind == "vibrance":
            # gray (desaturated) -> vivid saturated accent
            gray = (120, 120, 126)
            vivid = lerp(self.c_main, self.c_bright, t)
            return lerp(gray, vivid, t)
        return lerp(mix(self.c_main, self.bg, 0.30), self.c_bright, t)

    def redraw(self):
        W, H = max(1, self.w) * SS, self.h * SS
        img = Image.new("RGBA", (W, H), self.bg + (255,))
        glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        gd = ImageDraw.Draw(glow)

        th = int(12 * SS)
        pad = int(self.h / 2 * SS)
        y0 = H / 2 - th / 2
        y1 = H / 2 + th / 2
        x0, x1 = pad, W - pad
        rad = th / 2

        # empty track
        d.rounded_rectangle([x0, y0, x1, y1], radius=rad,
                            fill=mix(self.c_main, self.bg, 0.12) + (255,))

        # filled gradient up to the knob
        frac = self._frac()
        knob_x = x0 + frac * (x1 - x0)
        if knob_x > x0 + 1:
            fill_img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            fd = ImageDraw.Draw(fill_img)
            span = max(1, int(knob_x - x0))
            for i in range(span):
                t = i / span
                fd.line([(x0 + i, y0), (x0 + i, y1)], fill=self._track_color(t) + (255,))
            mask = Image.new("L", (W, H), 0)
            ImageDraw.Draw(mask).rounded_rectangle([x0, y0, knob_x, y1], radius=rad, fill=255)
            img.paste(fill_img, (0, 0), mask)

        # knob + glow
        kr = int(self.h / 2 * SS) - int(3 * SS)
        ky = H / 2
        kcol = self._track_color(frac)
        gd.ellipse([knob_x - kr * 1.6, ky - kr * 1.6, knob_x + kr * 1.6, ky + kr * 1.6],
                   fill=self.c_main + (180,))
        glow = glow.filter(ImageFilter.GaussianBlur(int(7 * SS)))
        img = Image.alpha_composite(glow, img)
        d = ImageDraw.Draw(img)
        d.ellipse([knob_x - kr, ky - kr, knob_x + kr, ky + kr], fill=(255, 255, 255, 255))
        d.ellipse([knob_x - kr + int(3 * SS), ky - kr + int(3 * SS),
                   knob_x + kr - int(3 * SS), ky + kr - int(3 * SS)],
                  fill=kcol + (255,))

        out = img.resize((max(1, self.w), self.h), Image.LANCZOS)
        self._photo = ImageTk.PhotoImage(out)
        self.delete("all")
        self.create_image(0, 0, anchor="nw", image=self._photo)


class GradientPanel(tk.Canvas):
    """A rounded panel filled with the live gamma/brightness/temperature preview."""

    def __init__(self, parent, *, width=360, height=92, bg="#121218",
                 gamma=1.0, brightness=1.0, temperature=6500, radius=16):
        super().__init__(parent, width=width, height=height, bg=bg,
                         highlightthickness=0, bd=0)
        self.w, self.h = width, height
        self.bg = hex_rgb(bg)
        self.radius = radius
        self.gamma, self.brightness, self.temperature = gamma, brightness, temperature
        self._photo = None
        self.bind("<Configure>", self._on_resize)
        self.redraw()

    def _on_resize(self, e):
        if abs(e.width - self.w) > 1:
            self.w = e.width
            self.redraw()

    def update_values(self, gamma, brightness, temperature):
        self.gamma, self.brightness, self.temperature = gamma, brightness, temperature
        self.redraw()

    def redraw(self):
        W, H = max(1, self.w) * SS, self.h * SS
        img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        rm, gm, bm = temperature_to_rgb(int(self.temperature))
        inv = 1.0 / max(0.01, self.gamma)
        grad = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        gd = ImageDraw.Draw(grad)
        for x in range(W):
            t = x / max(1, W - 1)
            base = (t ** inv) * self.brightness
            r = int(max(0, min(255, base * rm * 255)))
            g = int(max(0, min(255, base * gm * 255)))
            b = int(max(0, min(255, base * bm * 255)))
            gd.line([(x, 0), (x, H)], fill=(r, g, b, 255))
        mask = Image.new("L", (W, H), 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, W - 1, H - 1],
                                              radius=self.radius * SS, fill=255)
        img.paste(grad, (0, 0), mask)
        out = img.resize((max(1, self.w), self.h), Image.LANCZOS)
        self._photo = ImageTk.PhotoImage(out)
        self.delete("all")
        self.create_image(0, 0, anchor="nw", image=self._photo)
