"""Backend selection — picks the right gamma backend for the current OS."""

from __future__ import annotations

import sys

from .base import GammaBackend, Monitor

_backend: GammaBackend | None = None


def get_backend() -> GammaBackend:
    """Return a cached backend instance appropriate for this platform."""
    global _backend
    if _backend is not None:
        return _backend

    if sys.platform.startswith("win"):
        from .windows import WindowsBackend
        _backend = WindowsBackend()
    elif sys.platform == "darwin":
        from .macos import MacBackend
        _backend = MacBackend()
    elif sys.platform.startswith("linux"):
        from .linux import LinuxBackend
        _backend = LinuxBackend()
    else:
        _backend = _NullBackend()

    return _backend


class _NullBackend(GammaBackend):
    name = "Unsupported"

    @staticmethod
    def available() -> bool:
        return False

    def list_monitors(self) -> list[Monitor]:
        return [Monitor(id="", name="Unsupported platform", primary=True)]

    def set_ramp(self, monitor, ramp) -> bool:
        return False


__all__ = ["get_backend", "GammaBackend", "Monitor"]
