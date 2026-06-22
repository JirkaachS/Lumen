"""Linux backend.

Primary path: X11 XRandR via ctypes (libX11 + libXrandr). This supports full
arbitrary gamma ramps per CRTC, exactly like Windows/macOS.

Fallback path: the ``xrandr`` command line tool, which only exposes per-channel
gamma + a single brightness scalar. The engine can fold our parameters into that
form, so warm/cool tints and brightness still work, just with less precision.

Both paths are GPU-agnostic (NVIDIA / AMD / Intel) because XRandR is part of the
X server, not a vendor driver. Wayland sessions do not expose XRandR gamma; on
those we fall back to ``xrandr`` running through XWayland where available and
otherwise report failure gracefully.
"""

from __future__ import annotations

import ctypes
import os
import shutil
import subprocess

from ..engine import GammaRamp
from .base import GammaBackend, Monitor


class _XRandR:
    """Thin ctypes wrapper around the bits of libX11/libXrandr we need."""

    def __init__(self):
        self.x11 = ctypes.CDLL("libX11.so.6")
        self.xrr = ctypes.CDLL("libXrandr.so.2")

        self.x11.XOpenDisplay.restype = ctypes.c_void_p
        self.x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
        self.x11.XDefaultRootWindow.restype = ctypes.c_ulong
        self.x11.XDefaultRootWindow.argtypes = [ctypes.c_void_p]

        self.xrr.XRRGetScreenResourcesCurrent.restype = ctypes.c_void_p
        self.xrr.XRRGetScreenResourcesCurrent.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        self.xrr.XRRGetCrtcGammaSize.restype = ctypes.c_int
        self.xrr.XRRGetCrtcGammaSize.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        self.xrr.XRRAllocGamma.restype = ctypes.c_void_p
        self.xrr.XRRAllocGamma.argtypes = [ctypes.c_int]
        self.xrr.XRRSetCrtcGamma.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_void_p]
        self.xrr.XRRFreeGamma.argtypes = [ctypes.c_void_p]

        self.display = self.x11.XOpenDisplay(None)
        if not self.display:
            raise RuntimeError("cannot open X display")
        self.root = self.x11.XDefaultRootWindow(self.display)

    def crtcs(self) -> list[int]:
        # XRRScreenResources layout: we read the crtcs array via a small struct.
        class XRRScreenResources(ctypes.Structure):
            _fields_ = [
                ("timestamp", ctypes.c_ulong),
                ("configTimestamp", ctypes.c_ulong),
                ("ncrtc", ctypes.c_int),
                ("crtcs", ctypes.POINTER(ctypes.c_ulong)),
                ("noutput", ctypes.c_int),
                ("outputs", ctypes.POINTER(ctypes.c_ulong)),
                ("nmode", ctypes.c_int),
                ("modes", ctypes.c_void_p),
            ]

        res_ptr = self.xrr.XRRGetScreenResourcesCurrent(self.display, self.root)
        if not res_ptr:
            return []
        res = ctypes.cast(res_ptr, ctypes.POINTER(XRRScreenResources)).contents
        return [res.crtcs[i] for i in range(res.ncrtc)]

    def set_ramp(self, crtc: int, ramp: GammaRamp) -> bool:
        size = self.xrr.XRRGetCrtcGammaSize(self.display, crtc)
        if size <= 0:
            return False

        class XRRCrtcGamma(ctypes.Structure):
            _fields_ = [
                ("size", ctypes.c_int),
                ("red", ctypes.POINTER(ctypes.c_ushort)),
                ("green", ctypes.POINTER(ctypes.c_ushort)),
                ("blue", ctypes.POINTER(ctypes.c_ushort)),
            ]

        gamma_ptr = self.xrr.XRRAllocGamma(size)
        if not gamma_ptr:
            return False
        try:
            gamma = ctypes.cast(gamma_ptr, ctypes.POINTER(XRRCrtcGamma)).contents
            r, g, b = ramp.channels()
            for i in range(size):
                src = int(i * (len(r) - 1) / (size - 1)) if size > 1 else 0
                gamma.red[i] = r[src]
                gamma.green[i] = g[src]
                gamma.blue[i] = b[src]
            self.xrr.XRRSetCrtcGamma(self.display, crtc, gamma_ptr)
            self.x11.XFlush(self.display)
            return True
        finally:
            self.xrr.XRRFreeGamma(gamma_ptr)


class LinuxBackend(GammaBackend):
    def __init__(self):
        self._xrr = None
        self._mode = "none"
        try:
            self._xrr = _XRandR()
            self._mode = "xrandr-lib"
            self.name = "X11 XRandR"
        except Exception:
            if shutil.which("xrandr"):
                self._mode = "xrandr-cli"
                self.name = "xrandr (CLI)"
            else:
                self.name = "Unavailable"

    @staticmethod
    def available() -> bool:
        import sys
        if not sys.platform.startswith("linux"):
            return False
        if os.environ.get("DISPLAY"):
            return True
        return bool(shutil.which("xrandr"))

    def list_monitors(self) -> list[Monitor]:
        outputs = self._cli_outputs()
        if outputs:
            return outputs
        return [Monitor(id="", name="All Displays", primary=True)]

    def _cli_outputs(self) -> list[Monitor]:
        if not shutil.which("xrandr"):
            return []
        try:
            out = subprocess.run(
                ["xrandr", "--query"], capture_output=True, text=True, timeout=5
            ).stdout
        except Exception:
            return []
        monitors: list[Monitor] = []
        for line in out.splitlines():
            if " connected" in line:
                parts = line.split()
                name = parts[0]
                primary = "primary" in line
                monitors.append(Monitor(id=name, name=name, primary=primary))
        return monitors

    def set_ramp(self, monitor: Monitor | None, ramp: GammaRamp) -> bool:
        if self._mode == "xrandr-lib" and self._xrr:
            crtcs = self._xrr.crtcs()
            if not crtcs:
                return False
            ok = False
            for crtc in crtcs:
                ok = self._xrr.set_ramp(crtc, ramp) or ok
            return ok
        if self._mode == "xrandr-cli":
            return self._set_via_cli(monitor, ramp)
        return False

    def _set_via_cli(self, monitor: Monitor | None, ramp: GammaRamp) -> bool:
        rg, gg, bg = ramp.per_channel_gamma()
        targets: list[str] = []
        if monitor and monitor.id and monitor.id not in ("", "All Displays"):
            targets = [monitor.id]
        else:
            targets = [m.id for m in self._cli_outputs() if m.id] or []

        if not targets:
            return False
        ok = False
        for name in targets:
            cmd = [
                "xrandr", "--output", name,
                "--gamma", f"{rg:.3f}:{gg:.3f}:{bg:.3f}",
                "--brightness", f"{ramp.brightness:.3f}",
            ]
            try:
                subprocess.run(cmd, check=True, capture_output=True, timeout=5)
                ok = True
            except Exception:
                continue
        return ok
