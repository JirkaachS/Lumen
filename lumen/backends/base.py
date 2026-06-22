"""Backend abstraction for applying gamma ramps to physical displays."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from ..engine import GammaRamp


@dataclass(frozen=True)
class Monitor:
    """A display the backend can target.

    id       backend-specific handle/identifier used by set_ramp
    name     human friendly description (e.g. "NVIDIA GeForce RTX 4070")
    primary  whether this is the OS primary display
    """

    id: str
    name: str
    primary: bool = False

    @property
    def label(self) -> str:
        star = "\u2605  " if self.primary else ""
        return f"{star}{self.name}"


class GammaBackend(ABC):
    """Platform backend. Implementations live in windows.py / linux.py / macos.py."""

    #: short, human readable name of the backend ("Windows GDI", "X11 XRandR"...)
    name: str = "Generic"

    @staticmethod
    @abstractmethod
    def available() -> bool:
        """True if this backend can run on the current system."""

    @abstractmethod
    def list_monitors(self) -> list[Monitor]:
        """Enumerate targetable displays. Always returns at least one entry."""

    @abstractmethod
    def set_ramp(self, monitor: Monitor | None, ramp: GammaRamp) -> bool:
        """Push ``ramp`` to ``monitor`` (None = primary/default). Returns success."""

    def reset(self, monitor: Monitor | None) -> bool:
        """Restore the neutral ramp on a monitor."""
        return self.set_ramp(monitor, GammaRamp.neutral())
