# Changelog

## 1.0.2

### Added
- **Digital vibrance** (VibranceGUI-style saturation control), 0–100% with 50%
  neutral. NVIDIA via NVAPI on Windows and `nvidia-settings` on Linux.
- **Resolution / refresh-rate / scaling switching** with Default / Stretch /
  Center variants, a current-mode readout, and a 12-second confirm-or-auto-revert
  safety dialog so a bad mode can never lock you out.
- **Per-app automation ("Games")** — the standout improvement over VibranceGUI:
  add a process (e.g. `game.exe`) with a vibrance level and optional resolution;
  a background watcher applies it when the game launches and restores your
  desktop state when it exits. No extra dependencies (Toolhelp32 / `ps`).
- New **Display** and **Games** pages in the sidebar.

### Fixed
- Gamma dial handle is now centered on the arc (was drawn on the outer edge).

## 1.0.1

### Changed
- **Complete UI rework** for a modern, premium look:
  - New hero **circular gamma dial** with an antialiased, glowing gradient arc
    and a draggable handle (PIL-rendered, supersampled).
  - **Gradient "glow" sliders** for brightness and temperature — the temperature
    track now shows the real Kelvin color spectrum, with a soft glowing knob.
  - Smooth, rounded **live-preview panel** rendered with Pillow.
  - Redesigned preset cards with per-preset color dots, value pills and a
    one-tap "reset all".
  - Live accent recoloring across the dial, sliders and preview.

## 1.0.0

Complete ground-up rework of the original Windows-only "Gamma Control",
relaunched as **Lumen**.

### Added
- Cross-platform engine with pluggable backends: Windows (GDI), macOS
  (CoreGraphics), Linux (X11 XRandR + `xrandr` fallback). GPU-agnostic.
- Brightness and color-temperature controls alongside gamma.
- Live gradient preview of the current settings.
- Six presets (Night, Reading, Normal, Vivid, Gaming, Movie).
- Day/night scheduler.
- Launch-at-startup toggle in-app and an installer checkbox (per-user
  autostart on all three platforms).
- Smooth animated transitions and five accent themes.
- New generated icon set (ico / png / iconset).
- Windows installer (Inno Setup), Linux installer script + `.desktop`, macOS
  app/DMG build script.
- GitHub Actions workflow that builds and releases all three platforms on tag.

### Preserved from the original
- Slider-based gamma control and instant apply.
- Keyboard and mouse-button global hotkeys with toggle behaviour.
- Per-monitor selection, apply-to-all, restore-on-exit, keep-on-top,
  start-minimized.
- System tray with quick presets.
- The original "Game" gamma 2.50 behaviour lives on as the **Gaming** preset.
