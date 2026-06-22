"""Cross-platform settings storage and profile model for Lumen."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .engine import (
    BRIGHTNESS_DEFAULT,
    GAMMA_DEFAULT,
    TEMP_DEFAULT,
    clamp_brightness,
    clamp_gamma,
    clamp_temperature,
)


def config_dir() -> Path:
    """Return the per-user config directory, following platform conventions."""
    if sys.platform.startswith("win"):
        base = os.environ.get("APPDATA") or str(Path.home())
        folder = Path(base) / "Lumen"
    elif sys.platform == "darwin":
        folder = Path.home() / "Library" / "Application Support" / "Lumen"
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
        folder = Path(base) / "lumen"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def settings_path() -> Path:
    return config_dir() / "settings.json"


@dataclass
class Profile:
    """A named bundle of gamma + brightness + temperature, used by presets,
    hotkeys and the scheduler."""

    name: str = "Custom"
    gamma: float = GAMMA_DEFAULT
    brightness: float = BRIGHTNESS_DEFAULT
    temperature: int = TEMP_DEFAULT

    def normalized(self) -> "Profile":
        return Profile(
            name=self.name or "Custom",
            gamma=clamp_gamma(self.gamma),
            brightness=clamp_brightness(self.brightness),
            temperature=clamp_temperature(self.temperature),
        )


@dataclass
class Binding:
    """A hotkey (keyboard combo or 'mouse:<button>') mapped to a profile."""

    hotkey: str = ""
    gamma: float = GAMMA_DEFAULT
    brightness: float = BRIGHTNESS_DEFAULT
    temperature: int = TEMP_DEFAULT

    def profile(self) -> Profile:
        return Profile("Hotkey", self.gamma, self.brightness, self.temperature).normalized()


@dataclass
class GameRule:
    """Auto-apply a vibrance level (and optional resolution) while a process runs."""

    process: str = ""
    vibrance: int = 100
    change_resolution: bool = False
    width: int = 0
    height: int = 0
    freq: int = 0
    bpp: int = 32
    scaling: int = 0


# Built-in presets (the "Game" preset preserves the original 2.50 behaviour).
DEFAULT_PRESETS = [
    Profile("Night", 0.70, 0.85, 3600),
    Profile("Reading", 0.95, 0.95, 4500),
    Profile("Normal", 1.00, 1.00, 6500),
    Profile("Vivid", 1.40, 1.00, 6800),
    Profile("Gaming", 2.50, 1.00, 6500),
    Profile("Movie", 1.10, 0.90, 5200),
]


@dataclass
class Settings:
    gamma: float = GAMMA_DEFAULT
    brightness: float = BRIGHTNESS_DEFAULT
    temperature: int = TEMP_DEFAULT
    selected_monitor: str = ""
    apply_all_monitors: bool = False
    restore_on_exit: bool = True
    keep_on_top: bool = True
    start_minimized: bool = False
    smooth_transitions: bool = True
    accent: str = "amber"
    autostart: bool = False
    vibrance: int = 50
    schedule_enabled: bool = False
    schedule_day: str = "Normal"
    schedule_night: str = "Night"
    schedule_day_time: str = "07:00"
    schedule_night_time: str = "20:00"
    bindings: list[Binding] = field(default_factory=list)
    game_rules: list[GameRule] = field(default_factory=list)

    # ── persistence ──────────────────────────────────────────────────────
    def normalized(self) -> "Settings":
        self.gamma = clamp_gamma(self.gamma)
        self.brightness = clamp_brightness(self.brightness)
        self.temperature = clamp_temperature(self.temperature)
        return self

    def to_dict(self) -> dict:
        d = asdict(self)
        d["bindings"] = [asdict(b) for b in self.bindings]
        d["game_rules"] = [asdict(g) for g in self.game_rules]
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Settings":
        if not isinstance(d, dict):
            return cls()
        s = cls()
        for f in (
            "selected_monitor", "accent", "schedule_day", "schedule_night",
            "schedule_day_time", "schedule_night_time",
        ):
            if isinstance(d.get(f), str):
                setattr(s, f, d[f])
        for f in (
            "apply_all_monitors", "restore_on_exit", "keep_on_top",
            "start_minimized", "smooth_transitions", "autostart", "schedule_enabled",
        ):
            if f in d:
                setattr(s, f, bool(d[f]))
        s.gamma = clamp_gamma(d.get("gamma", GAMMA_DEFAULT))
        s.brightness = clamp_brightness(d.get("brightness", BRIGHTNESS_DEFAULT))
        s.temperature = clamp_temperature(d.get("temperature", TEMP_DEFAULT))
        try:
            s.vibrance = max(0, min(100, int(d.get("vibrance", 50))))
        except (TypeError, ValueError):
            s.vibrance = 50

        bindings = []
        for item in d.get("bindings", []) or []:
            if not isinstance(item, dict):
                continue
            hk = str(item.get("hotkey", "")).strip()
            if not hk:
                continue
            bindings.append(Binding(
                hotkey=hk,
                gamma=clamp_gamma(item.get("gamma", GAMMA_DEFAULT)),
                brightness=clamp_brightness(item.get("brightness", BRIGHTNESS_DEFAULT)),
                temperature=clamp_temperature(item.get("temperature", TEMP_DEFAULT)),
            ))
        s.bindings = bindings

        rules = []
        for item in d.get("game_rules", []) or []:
            if not isinstance(item, dict):
                continue
            proc = str(item.get("process", "")).strip()
            if not proc:
                continue
            try:
                rules.append(GameRule(
                    process=proc,
                    vibrance=max(0, min(100, int(item.get("vibrance", 100)))),
                    change_resolution=bool(item.get("change_resolution", False)),
                    width=int(item.get("width", 0)),
                    height=int(item.get("height", 0)),
                    freq=int(item.get("freq", 0)),
                    bpp=int(item.get("bpp", 32)),
                    scaling=int(item.get("scaling", 0)),
                ))
            except (TypeError, ValueError):
                continue
        s.game_rules = rules
        return s


def load_settings() -> Settings:
    path = settings_path()
    if not path.exists():
        return Settings()
    try:
        with path.open("r", encoding="utf-8") as f:
            return Settings.from_dict(json.load(f))
    except Exception:
        return Settings()


def save_settings(settings: Settings) -> None:
    try:
        with settings_path().open("w", encoding="utf-8") as f:
            json.dump(settings.to_dict(), f, indent=2)
    except Exception:
        pass
