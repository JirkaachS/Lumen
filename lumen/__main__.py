"""Lumen entry point. Run with ``python -m lumen`` or via the packaged binary."""

from __future__ import annotations

import argparse
import ctypes
import sys


def _set_app_id():
    # Group the taskbar icon under our own AppUserModelID on Windows.
    if sys.platform.startswith("win"):
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "JirkaachS.Lumen.App.1"
            )
        except Exception:
            pass


def main(argv=None):
    parser = argparse.ArgumentParser(prog="lumen", description="Display gamma, brightness and color temperature control.")
    parser.add_argument("--minimized", action="store_true",
                        help="start hidden in the system tray")
    args = parser.parse_args(argv)

    _set_app_id()

    from .app import LumenApp
    LumenApp(start_hidden=args.minimized).run()


if __name__ == "__main__":
    main()
