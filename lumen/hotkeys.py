"""Global hotkey + mouse-button dispatch.

Wraps the optional ``keyboard`` and ``mouse`` libraries. Both are available on
Windows and Linux (Linux needs root for global capture); on macOS global
capture is restricted, so the manager degrades gracefully and reports that
hotkeys are unavailable rather than crashing.
"""

from __future__ import annotations

import threading
import time

try:
    import keyboard as _keyboard
    _HAS_KB = True
except Exception:
    _keyboard = None
    _HAS_KB = False

try:
    import mouse as _mouse
    _HAS_MOUSE = True
except Exception:
    _mouse = None
    _HAS_MOUSE = False

MOUSE_DISPLAY = {
    "left": "Left Click",
    "right": "Right Click",
    "middle": "Middle Click",
    "x": "Mouse 4",
    "x2": "Mouse 5",
}


def hotkeys_available() -> bool:
    return _HAS_KB or _HAS_MOUSE


def keyboard_available() -> bool:
    return _HAS_KB


def mouse_available() -> bool:
    return _HAS_MOUSE


def format_hotkey(hk: str) -> str:
    if not hk:
        return ""
    if hk.startswith("mouse:"):
        btn = hk[6:]
        return MOUSE_DISPLAY.get(btn, f"Mouse {btn.title()}")
    return " + ".join(p.capitalize() for p in hk.split("+"))


class MouseDispatcher:
    """Single global mouse hook that fans out to per-button callbacks, with a
    record (one-shot) mode for capturing a button to bind."""

    def __init__(self):
        self._lock = threading.Lock()
        self._binds: dict[str, callable] = {}
        self._oneshot = None
        self._active = False
        self._last_fire: dict[str, float] = {}

    def _start(self):
        if self._active or not _HAS_MOUSE:
            return
        self._active = True
        _mouse.hook(self._dispatch)

    def _dispatch(self, event):
        if not _HAS_MOUSE or not isinstance(event, _mouse.ButtonEvent):
            return
        btn = event.button

        with self._lock:
            oneshot = self._oneshot
            bind_cb = self._binds.get(btn)

        if oneshot is not None:
            if btn == "left" and event.event_type == _mouse.UP:
                return
            with self._lock:
                self._oneshot = None
            oneshot(btn)
            return

        if btn in ("x", "x2"):
            if event.event_type != _mouse.UP:
                return
        else:
            if event.event_type != _mouse.DOWN:
                return

        if bind_cb is not None:
            now = time.monotonic()
            if now - self._last_fire.get(btn, 0.0) > 0.05:
                self._last_fire[btn] = now
                bind_cb()

    def set_oneshot(self, callback):
        self._start()
        with self._lock:
            self._oneshot = callback

    def cancel_oneshot(self):
        with self._lock:
            self._oneshot = None

    def set_bind(self, button: str, callback):
        self._start()
        with self._lock:
            self._binds[button] = callback

    def clear_binds(self):
        with self._lock:
            self._binds.clear()


class KeyboardManager:
    """Thin helper around the ``keyboard`` library with safe no-ops when absent."""

    def __init__(self):
        self._handles: list = []
        self._cancel_hook = None

    def add(self, combo: str, callback) -> bool:
        if not _HAS_KB:
            return False
        try:
            self._handles.append(_keyboard.add_hotkey(combo, callback))
            return True
        except Exception:
            return False

    def clear(self):
        if not _HAS_KB:
            return
        for h in self._handles:
            try:
                _keyboard.remove_hotkey(h)
            except Exception:
                pass
        self._handles.clear()

    def read_combo(self) -> str:
        if not _HAS_KB:
            return "esc"
        try:
            return _keyboard.read_hotkey(suppress=False)
        except Exception:
            return "esc"

    def hook_escape(self, callback):
        if not _HAS_KB:
            return
        self._cancel_hook = _keyboard.on_press_key("esc", callback, suppress=False)

    def unhook_escape(self):
        if not _HAS_KB or not self._cancel_hook:
            return
        try:
            _keyboard.unhook(self._cancel_hook)
        except Exception:
            pass
        self._cancel_hook = None
