"""Cross-platform "launch at login" registration.

Windows  -> HKCU\\...\\Run registry value
Linux    -> ~/.config/autostart/lumen.desktop (XDG autostart)
macOS    -> ~/Library/LaunchAgents/com.jirkaachs.lumen.plist

All three are per-user (no admin/root needed) and fully reversible.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_ID = "Lumen"
PLIST_LABEL = "com.jirkaachs.lumen"


def _launch_command() -> list[str]:
    """The command that should run at login."""
    if getattr(sys, "frozen", False):
        # Packaged executable (PyInstaller).
        return [sys.executable, "--minimized"]
    # Running from source: re-launch the module with the same interpreter.
    return [sys.executable, "-m", "lumen", "--minimized"]


def _quote(parts: list[str]) -> str:
    out = []
    for p in parts:
        out.append(f'"{p}"' if " " in p else p)
    return " ".join(out)


# ── Windows ─────────────────────────────────────────────────────────────────

def _win_set(enable: bool) -> bool:
    import winreg

    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0,
                             winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE)
    except FileNotFoundError:
        key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path)
    try:
        if enable:
            winreg.SetValueEx(key, APP_ID, 0, winreg.REG_SZ, _quote(_launch_command()))
        else:
            try:
                winreg.DeleteValue(key, APP_ID)
            except FileNotFoundError:
                pass
        return True
    finally:
        winreg.CloseKey(key)


def _win_enabled() -> bool:
    import winreg
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0, winreg.KEY_QUERY_VALUE,
        )
        try:
            winreg.QueryValueEx(key, APP_ID)
            return True
        except FileNotFoundError:
            return False
        finally:
            winreg.CloseKey(key)
    except FileNotFoundError:
        return False


# ── Linux ───────────────────────────────────────────────────────────────────

def _linux_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    folder = Path(base) / "autostart"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "lumen.desktop"


def _linux_set(enable: bool) -> bool:
    path = _linux_path()
    if enable:
        content = (
            "[Desktop Entry]\n"
            "Type=Application\n"
            "Name=Lumen\n"
            "Comment=Display gamma, brightness and color temperature\n"
            f"Exec={_quote(_launch_command())}\n"
            "Icon=lumen\n"
            "Terminal=false\n"
            "X-GNOME-Autostart-enabled=true\n"
        )
        path.write_text(content, encoding="utf-8")
    elif path.exists():
        path.unlink()
    return True


def _linux_enabled() -> bool:
    return _linux_path().exists()


# ── macOS ─────────────────────────────────────────────────────────────────

def _mac_path() -> Path:
    folder = Path.home() / "Library" / "LaunchAgents"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{PLIST_LABEL}.plist"


def _mac_set(enable: bool) -> bool:
    path = _mac_path()
    if enable:
        args = "".join(f"        <string>{a}</string>\n" for a in _launch_command())
        content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
            '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
            '<plist version="1.0">\n'
            "<dict>\n"
            "    <key>Label</key>\n"
            f"    <string>{PLIST_LABEL}</string>\n"
            "    <key>ProgramArguments</key>\n"
            "    <array>\n"
            f"{args}"
            "    </array>\n"
            "    <key>RunAtLoad</key>\n"
            "    <true/>\n"
            "</dict>\n"
            "</plist>\n"
        )
        path.write_text(content, encoding="utf-8")
    elif path.exists():
        path.unlink()
    return True


def _mac_enabled() -> bool:
    return _mac_path().exists()


# ── Public API ───────────────────────────────────────────────────────────────

def set_autostart(enable: bool) -> bool:
    try:
        if sys.platform.startswith("win"):
            return _win_set(enable)
        if sys.platform == "darwin":
            return _mac_set(enable)
        if sys.platform.startswith("linux"):
            return _linux_set(enable)
    except Exception:
        return False
    return False


def is_autostart_enabled() -> bool:
    try:
        if sys.platform.startswith("win"):
            return _win_enabled()
        if sys.platform == "darwin":
            return _mac_enabled()
        if sys.platform.startswith("linux"):
            return _linux_enabled()
    except Exception:
        return False
    return False
