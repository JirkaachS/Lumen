"""Windows backend using the GDI SetDeviceGammaRamp API.

GPU-agnostic: works with NVIDIA, AMD and Intel drivers since it talks to the
OS gamma-ramp interface rather than any vendor SDK. Some laptop panels driven
purely by the integrated GPU may reject ramps; that is a driver limitation, not
a Lumen one.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes

from ..engine import GammaRamp
from .base import GammaBackend, Monitor

DISPLAY_DEVICE_ACTIVE = 0x00000001
DISPLAY_DEVICE_PRIMARY_DEVICE = 0x00000004
DISPLAY_DEVICE_MIRRORING_DRIVER = 0x00000008


class DISPLAY_DEVICE(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("DeviceName", wintypes.WCHAR * 32),
        ("DeviceString", wintypes.WCHAR * 128),
        ("StateFlags", wintypes.DWORD),
        ("DeviceID", wintypes.WCHAR * 128),
        ("DeviceKey", wintypes.WCHAR * 128),
    ]


class WindowsBackend(GammaBackend):
    name = "Windows GDI"

    def __init__(self):
        self._user32 = ctypes.windll.user32
        self._gdi32 = ctypes.windll.gdi32

    @staticmethod
    def available() -> bool:
        import sys
        return sys.platform.startswith("win")

    def list_monitors(self) -> list[Monitor]:
        monitors: list[Monitor] = []
        for i in range(32):
            adapter = DISPLAY_DEVICE()
            adapter.cb = ctypes.sizeof(DISPLAY_DEVICE)
            if not self._user32.EnumDisplayDevicesW(None, i, ctypes.byref(adapter), 0):
                continue
            if not (adapter.StateFlags & DISPLAY_DEVICE_ACTIVE):
                continue
            if adapter.StateFlags & DISPLAY_DEVICE_MIRRORING_DRIVER:
                continue

            primary = bool(adapter.StateFlags & DISPLAY_DEVICE_PRIMARY_DEVICE)
            mon = DISPLAY_DEVICE()
            mon.cb = ctypes.sizeof(DISPLAY_DEVICE)
            name = ""
            if self._user32.EnumDisplayDevicesW(adapter.DeviceName, 0, ctypes.byref(mon), 0):
                name = mon.DeviceString.strip()
            name = name or adapter.DeviceString.strip() or "Display"
            monitors.append(Monitor(id=adapter.DeviceName, name=name, primary=primary))

        if not monitors:
            return [Monitor(id="", name="Default Display", primary=True)]
        monitors.sort(key=lambda m: not m.primary)
        return monitors

    def set_ramp(self, monitor: Monitor | None, ramp: GammaRamp) -> bool:
        device = monitor.id if monitor else ""
        hdc = None
        try:
            if device:
                hdc = self._gdi32.CreateDCW(device, None, None, None)
            else:
                hdc = self._user32.GetDC(0)
            if not hdc:
                return False

            table = (ctypes.c_ushort * 256) * 3
            arr = table()
            r, g, b = ramp.channels()
            for i in range(256):
                arr[0][i] = r[i]
                arr[1][i] = g[i]
                arr[2][i] = b[i]
            return bool(self._gdi32.SetDeviceGammaRamp(hdc, ctypes.byref(arr)))
        except Exception:
            return False
        finally:
            if hdc:
                if device:
                    self._gdi32.DeleteDC(hdc)
                else:
                    self._user32.ReleaseDC(0, hdc)
