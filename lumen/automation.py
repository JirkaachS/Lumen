"""
Per-application automation — the feature that makes VibranceGUI useful.

A lightweight background watcher polls the running process list. When a process
matching one of the user's rules appears, the app applies that rule's vibrance
(and optionally a resolution); when the process exits, it restores the previous
desktop state. No third-party dependencies: Windows uses the Toolhelp32
snapshot API, other platforms shell out to `ps`.
"""

from __future__ import annotations

import subprocess
import sys
import threading
import time


def running_processes() -> set[str]:
    """Return a set of lowercase executable names currently running."""
    if sys.platform.startswith("win"):
        return _win_processes()
    return _posix_processes()


def _win_processes() -> set[str]:
    import ctypes
    from ctypes import wintypes

    TH32CS_SNAPPROCESS = 0x00000002

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        ]

    k32 = ctypes.windll.kernel32
    snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap == -1:
        return set()
    names = set()
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        if k32.Process32FirstW(snap, ctypes.byref(entry)):
            while True:
                names.add(entry.szExeFile.lower())
                if not k32.Process32NextW(snap, ctypes.byref(entry)):
                    break
    finally:
        k32.CloseHandle(snap)
    return names


def _posix_processes() -> set[str]:
    try:
        out = subprocess.run(["ps", "-A", "-o", "comm="], capture_output=True,
                             text=True, timeout=5).stdout
        return {line.strip().split("/")[-1].lower() for line in out.splitlines() if line.strip()}
    except Exception:
        return set()


def normalize_name(name: str) -> str:
    name = (name or "").strip().lower()
    if name and not name.endswith(".exe") and sys.platform.startswith("win"):
        name += ".exe"
    return name


class AppWatcher:
    """Polls processes and fires on_start/on_stop for watched executable names."""

    def __init__(self, on_start, on_stop, interval: float = 2.0):
        self._on_start = on_start
        self._on_stop = on_stop
        self._interval = interval
        self._targets: set[str] = set()
        self._active: set[str] = set()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()

    def set_targets(self, names):
        with self._lock:
            self._targets = {normalize_name(n) for n in names if n}
            # forget active entries that are no longer watched
            self._active &= self._targets

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _loop(self):
        while not self._stop.is_set():
            try:
                with self._lock:
                    targets = set(self._targets)
                if targets:
                    procs = running_processes()
                    present = {t for t in targets if t in procs}
                    with self._lock:
                        started = present - self._active
                        stopped = self._active - present
                        self._active = present
                    for name in started:
                        self._safe(self._on_start, name)
                    for name in stopped:
                        self._safe(self._on_stop, name)
            except Exception:
                pass
            self._stop.wait(self._interval)

    @staticmethod
    def _safe(fn, name):
        try:
            fn(name)
        except Exception:
            pass
