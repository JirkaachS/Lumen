# Changelog

## 1.0.4

### Fixed
- **Process explorer selection now works** — rows were built as buttons with
  labels overlaid on top, which swallowed the click. Rows are now frames with
  the click bound across the whole row.

### Added
- **Real app icons in the process explorer**, extracted from each executable via
  the Win32 icon API (falls back to a letter badge when an icon can't be read).

## 1.0.3

### Added
- **Process explorer** on the Games page — browse running apps (those with a
  visible window) and pick one instead of typing the executable name.

### Changed
- **Max digital vibrance raised to 200%** (100% = neutral, 200% = GPU max).
- **Resolution picker is now searchable and scrollable** via a popup, and the
  list is far shorter: scaling (Default / Stretch / Center) moved to its own
  control so modes aren't tripled (441 → 147 entries here).

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
