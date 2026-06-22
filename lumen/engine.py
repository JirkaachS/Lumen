"""
Lumen gamma engine.

Turns three intuitive, GPU-agnostic parameters into a full 256-entry RGB
gamma ramp that every platform backend can consume:

    gamma        0.30 .. 2.50   (contrast / midtone curve, 1.00 = neutral)
    brightness   0.10 .. 1.00   (output scale, 1.00 = full)
    temperature  3000 .. 10000  (Kelvin white point, 6500 = neutral daylight)

The ramp is intentionally backend-neutral: a list of three channels, each a
list of 256 integers in the 0..65535 range. Backends decide how to push it to
the hardware (Windows SetDeviceGammaRamp, X11 XRandR, macOS CoreGraphics).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

GAMMA_MIN = 0.30
GAMMA_MAX = 2.50
GAMMA_DEFAULT = 1.00

BRIGHTNESS_MIN = 0.10
BRIGHTNESS_MAX = 1.00
BRIGHTNESS_DEFAULT = 1.00

TEMP_MIN = 3000
TEMP_MAX = 10000
TEMP_DEFAULT = 6500

RAMP_SIZE = 256
RAMP_MAX = 65535


def clamp(value, lo, hi, default):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(value):
        return default
    return max(lo, min(hi, value))


def clamp_gamma(v):
    return clamp(v, GAMMA_MIN, GAMMA_MAX, GAMMA_DEFAULT)


def clamp_brightness(v):
    return clamp(v, BRIGHTNESS_MIN, BRIGHTNESS_MAX, BRIGHTNESS_DEFAULT)


def clamp_temperature(v):
    return int(clamp(v, TEMP_MIN, TEMP_MAX, TEMP_DEFAULT))


# ── Color temperature → linear RGB multipliers ──────────────────────────────
# Based on Tanner Helland's widely used approximation, normalised so that the
# brightest channel is always 1.0 (so temperature only *tints*, it never dims —
# brightness is handled separately).

def temperature_to_rgb(kelvin: int) -> tuple[float, float, float]:
    kelvin = clamp_temperature(kelvin)
    t = kelvin / 100.0

    if t <= 66:
        r = 255.0
    else:
        r = 329.698727446 * ((t - 60) ** -0.1332047592)

    if t <= 66:
        g = 99.4708025861 * math.log(t) - 161.1195681661 if t > 0 else 0.0
    else:
        g = 288.1221695283 * ((t - 60) ** -0.0755148492)

    if t >= 66:
        b = 255.0
    elif t <= 19:
        b = 0.0
    else:
        b = 138.5177312231 * math.log(t - 10) - 305.0447927307

    r = max(0.0, min(255.0, r))
    g = max(0.0, min(255.0, g))
    b = max(0.0, min(255.0, b))

    peak = max(r, g, b) or 255.0
    return (r / peak, g / peak, b / peak)


@dataclass
class GammaRamp:
    """A backend-neutral 3x256 gamma ramp plus the params that produced it."""

    gamma: float = GAMMA_DEFAULT
    brightness: float = BRIGHTNESS_DEFAULT
    temperature: int = TEMP_DEFAULT
    red: list[int] = field(default_factory=list)
    green: list[int] = field(default_factory=list)
    blue: list[int] = field(default_factory=list)

    @classmethod
    def neutral(cls) -> "GammaRamp":
        return cls.build(GAMMA_DEFAULT, BRIGHTNESS_DEFAULT, TEMP_DEFAULT)

    @classmethod
    def build(cls, gamma=GAMMA_DEFAULT, brightness=BRIGHTNESS_DEFAULT,
              temperature=TEMP_DEFAULT) -> "GammaRamp":
        g = clamp_gamma(gamma)
        b = clamp_brightness(brightness)
        k = clamp_temperature(temperature)
        rm, gm, bm = temperature_to_rgb(k)

        red, green, blue = [], [], []
        inv_gamma = 1.0 / g
        for i in range(RAMP_SIZE):
            base = (i / (RAMP_SIZE - 1)) ** inv_gamma
            scaled = base * b
            red.append(_q(scaled * rm))
            green.append(_q(scaled * gm))
            blue.append(_q(scaled * bm))

        return cls(gamma=g, brightness=b, temperature=k,
                   red=red, green=green, blue=blue)

    def channels(self) -> tuple[list[int], list[int], list[int]]:
        return self.red, self.green, self.blue

    def per_channel_gamma(self) -> tuple[float, float, float]:
        """Effective per-channel gamma for backends that only take gamma/brightness
        (e.g. the xrandr CLI fallback)."""
        rm, gm, bm = temperature_to_rgb(self.temperature)

        def fold(mult):
            # Temperature tint folded into a gamma exponent so warm tones still
            # read as a reddish cast under gamma-only backends.
            mult = max(0.05, min(1.0, mult))
            return self.gamma * (1.0 + (1.0 - mult) * 0.6)

        return fold(rm), fold(gm), fold(bm)


def _q(value: float) -> int:
    return max(0, min(RAMP_MAX, int(round(value * RAMP_MAX))))
