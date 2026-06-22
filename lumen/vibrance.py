"""
Digital vibrance (saturation) control — the VibranceGUI-style feature.

True digital vibrance lives in the GPU's color pipeline, so it needs vendor
APIs rather than a gamma ramp:

    NVIDIA  -> NVAPI DVC (NvAPI_DISP_Get/SetDVCLevelEx), level 0..100, 50 = neutral
    AMD     -> ADL saturation (best effort; many drivers expose it via the
               Radeon panel only — reported as unavailable if ADL isn't present)
    Linux   -> `nvidia-settings -a [gpu:0]/DigitalVibrance` (0..1023, 0 = neutral)

The UI works in a friendly 0..100% scale (50% = neutral) and each backend maps
that onto its native range.
"""

from __future__ import annotations

import ctypes
import shutil
import subprocess
import sys
from ctypes import POINTER, byref, c_int, c_uint, c_void_p

NEUTRAL_PERCENT = 100  # UI scale is 0..200%, 100% = neutral, 200% = GPU max


class VibranceBackend:
    name = "Unavailable"

    def available(self) -> bool:
        return False

    def get_percent(self) -> int:
        return NEUTRAL_PERCENT

    def set_percent(self, percent: int) -> bool:
        return False

    def reset(self) -> bool:
        return self.set_percent(NEUTRAL_PERCENT)


# ── NVIDIA (Windows, NVAPI) ──────────────────────────────────────────────────

class _DVC(ctypes.Structure):
    _fields_ = [
        ("version", c_uint),
        ("currentLevel", c_int),
        ("minLevel", c_int),
        ("maxLevel", c_int),
        ("defaultLevel", c_int),
    ]


class NvidiaVibrance(VibranceBackend):
    name = "NVIDIA Digital Vibrance"

    _ID_INIT = 0x0150E828
    _ID_ENUM = 0x9ABDD40D
    _ID_GET = 0x0E45002D
    _ID_SET = 0x4A82C2B1

    def __init__(self):
        self._ok = False
        self._handles: list[c_void_p] = []
        self._min = 0
        self._max = 100
        self._default = NEUTRAL_PERCENT
        try:
            self._dll = ctypes.WinDLL("nvapi64.dll" if sys.maxsize > 2**32 else "nvapi.dll")
            q = getattr(self._dll, "nvapi_QueryInterface")
            q.restype = c_void_p
            q.argtypes = [c_uint]
            self._q = q
            self._init()
        except Exception:
            self._ok = False

    def _fn(self, fid, restype, *args):
        addr = self._q(fid)
        if not addr:
            return None
        return ctypes.CFUNCTYPE(restype, *args)(addr)

    def _init(self):
        Initialize = self._fn(self._ID_INIT, c_int)
        self._EnumDisp = self._fn(self._ID_ENUM, c_int, c_int, POINTER(c_void_p))
        self._Get = self._fn(self._ID_GET, c_int, c_void_p, c_uint, POINTER(_DVC))
        self._Set = self._fn(self._ID_SET, c_int, c_void_p, c_uint, POINTER(_DVC))
        if not (Initialize and self._EnumDisp and self._Get and self._Set):
            return
        if Initialize() != 0:
            return

        self._ver = ctypes.sizeof(_DVC) | (1 << 16)
        i = 0
        while True:
            h = c_void_p()
            if self._EnumDisp(i, byref(h)) != 0:
                break
            self._handles.append(h)
            i += 1
            if i > 16:
                break
        if not self._handles:
            return

        info = _DVC()
        info.version = self._ver
        if self._Get(self._handles[0], 0, byref(info)) == 0:
            self._min, self._max, self._default = info.minLevel, info.maxLevel, info.defaultLevel
        self._ok = True

    def available(self) -> bool:
        return self._ok

    def _to_level(self, percent: int) -> int:
        percent = max(0, min(200, int(percent)))
        return int(round(self._min + (percent / 200.0) * (self._max - self._min)))

    def _to_percent(self, level: int) -> int:
        span = max(1, self._max - self._min)
        return int(round((level - self._min) / span * 200))

    def get_percent(self) -> int:
        if not self._ok:
            return NEUTRAL_PERCENT
        info = _DVC()
        info.version = self._ver
        if self._Get(self._handles[0], 0, byref(info)) == 0:
            return self._to_percent(info.currentLevel)
        return NEUTRAL_PERCENT

    def set_percent(self, percent: int) -> bool:
        if not self._ok:
            return False
        level = self._to_level(percent)
        ok = False
        for h in self._handles:
            info = _DVC()
            info.version = self._ver
            info.currentLevel = level
            if self._Set(h, 0, byref(info)) == 0:
                ok = True
        return ok


# ── NVIDIA / AMD on Linux via CLI ────────────────────────────────────────────

class LinuxNvidiaVibrance(VibranceBackend):
    name = "nvidia-settings vibrance"
    _MAX = 1023  # nvidia-settings DigitalVibrance range is -1024..1023, 0 neutral

    def available(self) -> bool:
        return bool(shutil.which("nvidia-settings"))

    def set_percent(self, percent: int) -> bool:
        percent = max(0, min(200, int(percent)))
        # 100% -> 0 (neutral); 200% -> +MAX; 0% -> -MAX
        value = int(round((percent - 100) / 100.0 * self._MAX))
        try:
            subprocess.run(
                ["nvidia-settings", "-a", f"[gpu:0]/DigitalVibrance={value}"],
                check=True, capture_output=True, timeout=5,
            )
            return True
        except Exception:
            return False


# ── factory ──────────────────────────────────────────────────────────────────

_backend: VibranceBackend | None = None


def get_vibrance_backend() -> VibranceBackend:
    global _backend
    if _backend is not None:
        return _backend

    if sys.platform.startswith("win"):
        nv = NvidiaVibrance()
        _backend = nv if nv.available() else VibranceBackend()
    elif sys.platform.startswith("linux"):
        ln = LinuxNvidiaVibrance()
        _backend = ln if ln.available() else VibranceBackend()
    else:
        _backend = VibranceBackend()  # macOS has no public vibrance API
    return _backend
