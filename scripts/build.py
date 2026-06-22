"""
Cross-platform build helper for Lumen.

Usage:
    python scripts/build.py

Produces a single-file (Windows/macOS) or single-folder (Linux) bundle in
dist/ via PyInstaller. Regenerates icons first so the build is reproducible.

After a Windows build you can wrap dist/Lumen.exe with the Inno Setup script in
installer/windows/lumen.iss to get an installer with an autostart option.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "lumen" / "assets"


def run(cmd: list[str]):
    print(">", " ".join(cmd))
    subprocess.run(cmd, check=True, cwd=ROOT)


def main():
    run([sys.executable, str(ROOT / "scripts" / "make_icons.py")])

    sep = ";" if sys.platform.startswith("win") else ":"
    add_data = f"{ASSETS}{sep}lumen/assets"

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean", "--windowed",
        "--name", "Lumen",
        "--add-data", add_data,
        "--collect-data", "customtkinter",
        "--paths", str(ROOT),
    ]

    if sys.platform.startswith("win"):
        cmd += ["--onefile", "--icon", str(ASSETS / "lumen.ico")]
    elif sys.platform == "darwin":
        icns = ASSETS / "lumen.icns"
        cmd += ["--onefile", "--osx-bundle-identifier", "com.jirkaachs.lumen"]
        if icns.exists():
            cmd += ["--icon", str(icns)]
    else:  # linux: one-folder is friendlier for .desktop installs
        png = ASSETS / "lumen.png"
        if png.exists():
            cmd += ["--icon", str(png)]

    cmd += [str(ROOT / "scripts" / "_entry.py")]

    # Generate the PyInstaller entry shim (gitignored, created at build time).
    (ROOT / "scripts" / "_entry.py").write_text(
        "from lumen.__main__ import main\nmain()\n", encoding="utf-8"
    )

    run(cmd)
    print("\nBuild complete ->", ROOT / "dist")


if __name__ == "__main__":
    main()
