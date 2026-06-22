"""macOS backend using CoreGraphics gamma APIs.

CGSetDisplayTransferByTable accepts an arbitrary float ramp per channel, so we
get the same full-fidelity control as Windows/X11. GPU-agnostic: CoreGraphics
sits above whatever GPU (Apple Silicon, AMD, Intel) drives the panel.
"""

from __future__ import annotations

import ctypes

from ..engine import RAMP_MAX, GammaRamp
from .base import GammaBackend, Monitor

_MAX_DISPLAYS = 16


class MacBackend(GammaBackend):
    name = "macOS CoreGraphics"

    def __init__(self):
        self._cg = ctypes.CDLL(
            "/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics"
        )
        self._cg.CGGetActiveDisplayList.argtypes = [
            ctypes.c_uint32,
            ctypes.POINTER(ctypes.c_uint32),
            ctypes.POINTER(ctypes.c_uint32),
        ]
        self._cg.CGSetDisplayTransferByTable.argtypes = [
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.POINTER(ctypes.c_float),
            ctypes.POINTER(ctypes.c_float),
            ctypes.POINTER(ctypes.c_float),
        ]
        self._cg.CGDisplayRestoreColorSyncSettings.argtypes = []
        self._cg.CGMainDisplayID.restype = ctypes.c_uint32

    @staticmethod
    def available() -> bool:
        import sys
        return sys.platform == "darwin"

    def _display_ids(self) -> list[int]:
        ids = (ctypes.c_uint32 * _MAX_DISPLAYS)()
        count = ctypes.c_uint32(0)
        if self._cg.CGGetActiveDisplayList(_MAX_DISPLAYS, ids, ctypes.byref(count)) != 0:
            return [self._cg.CGMainDisplayID()]
        return [ids[i] for i in range(count.value)]

    def list_monitors(self) -> list[Monitor]:
        ids = self._display_ids()
        main = self._cg.CGMainDisplayID()
        monitors = []
        for idx, did in enumerate(ids):
            primary = did == main
            label = "Built-in / Main Display" if primary else f"Display {idx + 1}"
            monitors.append(Monitor(id=str(did), name=label, primary=primary))
        return monitors or [Monitor(id=str(main), name="Main Display", primary=True)]

    def set_ramp(self, monitor: Monitor | None, ramp: GammaRamp) -> bool:
        if monitor and monitor.id:
            try:
                targets = [int(monitor.id)]
            except ValueError:
                targets = self._display_ids()
        else:
            targets = self._display_ids()

        r, g, b = ramp.channels()
        n = len(r)
        rf = (ctypes.c_float * n)(*[v / RAMP_MAX for v in r])
        gf = (ctypes.c_float * n)(*[v / RAMP_MAX for v in g])
        bf = (ctypes.c_float * n)(*[v / RAMP_MAX for v in b])

        ok = False
        for did in targets:
            try:
                res = self._cg.CGSetDisplayTransferByTable(did, n, rf, gf, bf)
                ok = (res == 0) or ok
            except Exception:
                continue
        return ok

    def reset(self, monitor: Monitor | None) -> bool:
        try:
            self._cg.CGDisplayRestoreColorSyncSettings()
            return True
        except Exception:
            return super().reset(monitor)
