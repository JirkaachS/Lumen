"""Color palette, accent options and font helpers for the Lumen UI."""

from __future__ import annotations

import sys

# ── Base dark surface palette ────────────────────────────────────────────────
BG = "#0B0B0F"
SURF = "#121218"
SURF2 = "#181820"
SURF3 = "#21212B"
SURF4 = "#2A2A36"
BORDER = "#2C2C38"
BORDER2 = "#3C3C4A"
TEXT = "#F2F2F5"
MUTED = "#7A7A88"
MUTED2 = "#4A4A57"
DANGER = "#E0556B"
WARN = "#FBBF24"
SUCCESS = "#43C59E"
WHITE = "#FFFFFF"

# ── Accents (user-selectable) ────────────────────────────────────────────────
ACCENTS = {
    "amber":  {"main": "#F5A623", "bright": "#FFC14D", "dim": "#3A2A0C", "danger_bg": "#2A1010"},
    "cyan":   {"main": "#37C7D4", "bright": "#67E0EA", "dim": "#0C2A2E", "danger_bg": "#2A1018"},
    "violet": {"main": "#9B7BFF", "bright": "#B9A2FF", "dim": "#1E1638", "danger_bg": "#2A1020"},
    "emerald":{"main": "#43C59E", "bright": "#6FE0BF", "dim": "#0E2A22", "danger_bg": "#2A1018"},
    "rose":   {"main": "#FF6B8B", "bright": "#FF94AB", "dim": "#34121C", "danger_bg": "#2A1018"},
}
DEFAULT_ACCENT = "amber"


class Accent:
    """Live accent color holder; rebuilt when the user changes accent."""

    def __init__(self, name: str = DEFAULT_ACCENT):
        self.set(name)

    def set(self, name: str):
        data = ACCENTS.get(name, ACCENTS[DEFAULT_ACCENT])
        self.name = name if name in ACCENTS else DEFAULT_ACCENT
        self.main = data["main"]
        self.bright = data["bright"]
        self.dim = data["dim"]
        self.danger_bg = data["danger_bg"]


def font_family() -> str:
    if sys.platform.startswith("win"):
        return "Segoe UI"
    if sys.platform == "darwin":
        return "SF Pro Text"
    return "Sans"


def heavy_family() -> str:
    if sys.platform.startswith("win"):
        return "Segoe UI Semibold"
    if sys.platform == "darwin":
        return "SF Pro Display"
    return "Sans"


def f(size: int, weight: str = "normal", heavy: bool = False):
    fam = heavy_family() if heavy else font_family()
    if weight == "bold":
        return (fam, size, "bold")
    return (fam, size)
