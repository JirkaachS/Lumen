"""
Display mode (resolution / refresh-rate / scaling) enumeration and switching.

Windows: EnumDisplaySettingsExW + ChangeDisplaySettingsExW, including the
Default / Stretch / Center scaling variants shown by tools like VibranceGUI.
Linux: best-effort via the `xrandr` CLI.
macOS: not yet supported (reports an empty list).

Mode changes are applied dynamically (not written to the registry) so they can
be reverted cleanly; the UI wraps apply() in a confirm-or-auto-revert flow.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass

SCALING_NAMES = {0: "Default", 1: "Stretch", 2: "Center"}


@dataclass(frozen=True)
class DisplayMode:
    width: int
    height: int
    freq: int
    bpp: int = 32
    scaling: int = 0

    @property
    def label(self) -> str:
        return (f"{self.width} x {self.height} @ {self.freq} hz "
                f"({self.bpp} bit, {SCALING_NAMES.get(self.scaling, 'Default')})")

    @property
    def key(self) -> str:
        return f"{self.width}x{self.height}@{self.freq}:{self.bpp}:{self.scaling}"


def list_modes(device: str | None) -> list[DisplayMode]:
    if sys.platform.startswith("win"):
        return _win_list(device)
    if sys.platform.startswith("linux"):
        return _linux_list(device)
    return []


def current_mode(device: str | None) -> DisplayMode | None:
    if sys.platform.startswith("win"):
        return _win_current(device)
    return None


def apply_mode(device: str | None, mode: DisplayMode) -> tuple[bool, str]:
    if sys.platform.startswith("win"):
        return _win_apply(device, mode)
    if sys.platform.startswith("linux"):
        return _linux_apply(device, mode)
    return False, "Resolution switching isn't supported on this platform."


def restore(device: str | None) -> bool:
    if sys.platform.startswith("win"):
        return _win_restore(device)
    return False


# ── Windows ──────────────────────────────────────────────────────────────────

if sys.platform.startswith("win"):
    import ctypes
    from ctypes import wintypes

    _user32 = ctypes.windll.user32

    class _POINTL(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

    class _DEVMODE(ctypes.Structure):
        _fields_ = [
            ("dmDeviceName", wintypes.WCHAR * 32),
            ("dmSpecVersion", wintypes.WORD),
            ("dmDriverVersion", wintypes.WORD),
            ("dmSize", wintypes.WORD),
            ("dmDriverExtra", wintypes.WORD),
            ("dmFields", wintypes.DWORD),
            ("dmPosition", _POINTL),
            ("dmDisplayOrientation", wintypes.DWORD),
            ("dmDisplayFixedOutput", wintypes.DWORD),
            ("dmColor", ctypes.c_short),
            ("dmDuplex", ctypes.c_short),
            ("dmYResolution", ctypes.c_short),
            ("dmTTOption", ctypes.c_short),
            ("dmCollate", ctypes.c_short),
            ("dmFormName", wintypes.WCHAR * 32),
            ("dmLogPixels", wintypes.WORD),
            ("dmBitsPerPel", wintypes.DWORD),
            ("dmPelsWidth", wintypes.DWORD),
            ("dmPelsHeight", wintypes.DWORD),
            ("dmDisplayFlags", wintypes.DWORD),
            ("dmDisplayFrequency", wintypes.DWORD),
            ("dmICMMethod", wintypes.DWORD),
            ("dmICMIntent", wintypes.DWORD),
            ("dmMediaType", wintypes.DWORD),
            ("dmDitherType", wintypes.DWORD),
            ("dmReserved1", wintypes.DWORD),
            ("dmReserved2", wintypes.DWORD),
            ("dmPanningWidth", wintypes.DWORD),
            ("dmPanningHeight", wintypes.DWORD),
        ]

    ENUM_CURRENT_SETTINGS = -1
    DM_BITSPERPEL = 0x00040000
    DM_PELSWIDTH = 0x00080000
    DM_PELSHEIGHT = 0x00100000
    DM_DISPLAYFREQUENCY = 0x00400000
    DM_DISPLAYFIXEDOUTPUT = 0x20000000
    CDS_TEST = 0x02
    DISP_CHANGE_SUCCESSFUL = 0
    _DISP_ERRORS = {
        0: "OK", 1: "Restart required", -1: "Mode change failed",
        -2: "Invalid mode", -3: "Flags conflict", -4: "Bad flags",
        -5: "Bad parameter", -6: "Bad DEVMODE",
    }

    def _dev(device):
        return device if device else None

    def _win_current(device):
        dm = _DEVMODE()
        dm.dmSize = ctypes.sizeof(_DEVMODE)
        if not _user32.EnumDisplaySettingsW(_dev(device), ENUM_CURRENT_SETTINGS, ctypes.byref(dm)):
            return None
        return DisplayMode(dm.dmPelsWidth, dm.dmPelsHeight, dm.dmDisplayFrequency,
                           dm.dmBitsPerPel, dm.dmDisplayFixedOutput)

    def _win_list(device):
        seen = {}
        i = 0
        while True:
            dm = _DEVMODE()
            dm.dmSize = ctypes.sizeof(_DEVMODE)
            if not _user32.EnumDisplaySettingsW(_dev(device), i, ctypes.byref(dm)):
                break
            i += 1
            if dm.dmBitsPerPel < 32 or dm.dmDisplayFrequency <= 1:
                continue
            base = (dm.dmPelsWidth, dm.dmPelsHeight, dm.dmDisplayFrequency, dm.dmBitsPerPel)
            seen[base] = True
            if i > 4000:
                break

        modes: list[DisplayMode] = []
        for (w, h, f, bpp) in sorted(seen, key=lambda b: (-b[0], -b[1], -b[2])):
            for scaling in (0, 1, 2):
                modes.append(DisplayMode(w, h, f, bpp, scaling))
        return modes

    def _build_devmode(mode: DisplayMode):
        dm = _DEVMODE()
        dm.dmSize = ctypes.sizeof(_DEVMODE)
        dm.dmPelsWidth = mode.width
        dm.dmPelsHeight = mode.height
        dm.dmDisplayFrequency = mode.freq
        dm.dmBitsPerPel = mode.bpp
        dm.dmDisplayFixedOutput = mode.scaling
        dm.dmFields = (DM_PELSWIDTH | DM_PELSHEIGHT | DM_DISPLAYFREQUENCY
                       | DM_BITSPERPEL | DM_DISPLAYFIXEDOUTPUT)
        return dm

    def _win_apply(device, mode):
        dm = _build_devmode(mode)
        test = _user32.ChangeDisplaySettingsExW(_dev(device), ctypes.byref(dm), None, CDS_TEST, None)
        if test != DISP_CHANGE_SUCCESSFUL:
            return False, _DISP_ERRORS.get(test, f"Error {test}")
        res = _user32.ChangeDisplaySettingsExW(_dev(device), ctypes.byref(dm), None, 0, None)
        if res == DISP_CHANGE_SUCCESSFUL:
            return True, "Applied"
        return False, _DISP_ERRORS.get(res, f"Error {res}")

    def _win_restore(device):
        # Passing NULL DEVMODE restores the registry (default) settings.
        return _user32.ChangeDisplaySettingsExW(_dev(device), None, None, 0, None) == DISP_CHANGE_SUCCESSFUL


# ── Linux (xrandr) ───────────────────────────────────────────────────────────

def _linux_outputs_modes(device):
    if not shutil.which("xrandr"):
        return []
    try:
        out = subprocess.run(["xrandr", "--query"], capture_output=True, text=True, timeout=5).stdout
    except Exception:
        return []
    modes = []
    cur_out = None
    for line in out.splitlines():
        if " connected" in line:
            cur_out = line.split()[0]
        elif line.startswith("   ") and cur_out and (device in (None, "", cur_out)):
            parts = line.split()
            if "x" in parts[0]:
                w, h = parts[0].split("x")[:2]
                for rate in parts[1:]:
                    r = rate.rstrip("*+")
                    try:
                        modes.append(DisplayMode(int(w), int(h), int(round(float(r))), 32, 0))
                    except ValueError:
                        continue
    return modes


def _linux_list(device):
    seen = {}
    for m in _linux_outputs_modes(device):
        seen[(m.width, m.height, m.freq)] = m
    return list(seen.values())


def _linux_apply(device, mode):
    if not shutil.which("xrandr"):
        return False, "xrandr not found"
    out = device or _first_connected_output()
    if not out:
        return False, "No output"
    try:
        subprocess.run(["xrandr", "--output", out, "--mode", f"{mode.width}x{mode.height}",
                        "--rate", str(mode.freq)], check=True, capture_output=True, timeout=8)
        return True, "Applied"
    except Exception as e:
        return False, str(e)


def _first_connected_output():
    try:
        out = subprocess.run(["xrandr", "--query"], capture_output=True, text=True, timeout=5).stdout
        for line in out.splitlines():
            if " connected" in line:
                return line.split()[0]
    except Exception:
        pass
    return None
