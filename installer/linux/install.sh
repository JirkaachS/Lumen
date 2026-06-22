#!/usr/bin/env bash
#
# Lumen — Linux installer (per-user, no root required).
#
# Installs the PyInstaller one-folder build (or a source checkout) into
# ~/.local/share/lumen, drops a launcher into ~/.local/bin, registers a
# desktop entry + icon, and optionally enables autostart.
#
# Usage:
#   ./install.sh             install
#   ./install.sh --autostart install and enable launch-at-login
#   ./install.sh --uninstall remove everything
#
set -euo pipefail

APP="lumen"
PREFIX="${HOME}/.local"
SHARE="${PREFIX}/share/${APP}"
BIN="${PREFIX}/bin"
DESKTOP_DIR="${PREFIX}/share/applications"
ICON_DIR="${PREFIX}/share/icons/hicolor/256x256/apps"
AUTOSTART_DIR="${HOME}/.config/autostart"
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "${HERE}/../.." && pwd)"

uninstall() {
    echo "Removing Lumen…"
    rm -rf "${SHARE}"
    rm -f "${BIN}/${APP}"
    rm -f "${DESKTOP_DIR}/${APP}.desktop"
    rm -f "${ICON_DIR}/${APP}.png"
    rm -f "${AUTOSTART_DIR}/${APP}.desktop"
    echo "Done."
}

if [[ "${1:-}" == "--uninstall" ]]; then
    uninstall
    exit 0
fi

echo "Installing Lumen to ${SHARE}…"
mkdir -p "${SHARE}" "${BIN}" "${DESKTOP_DIR}" "${ICON_DIR}"

if [[ -d "${ROOT}/dist/Lumen" ]]; then
    # PyInstaller one-folder build
    cp -r "${ROOT}/dist/Lumen/." "${SHARE}/"
    LAUNCH="${SHARE}/Lumen"
elif [[ -f "${ROOT}/dist/Lumen" ]]; then
    cp "${ROOT}/dist/Lumen" "${SHARE}/Lumen"
    LAUNCH="${SHARE}/Lumen"
else
    # Source install: requires python3 + dependencies on PATH
    cp -r "${ROOT}/lumen" "${SHARE}/lumen"
    LAUNCH="python3 -m lumen"
fi

# Launcher script on PATH
cat > "${BIN}/${APP}" <<EOF
#!/usr/bin/env bash
cd "${SHARE}"
exec ${LAUNCH} "\$@"
EOF
chmod +x "${BIN}/${APP}"

# Icon + desktop entry
cp "${ROOT}/lumen/assets/lumen_256.png" "${ICON_DIR}/${APP}.png" 2>/dev/null || true
cp "${HERE}/lumen.desktop" "${DESKTOP_DIR}/${APP}.desktop"
chmod +x "${DESKTOP_DIR}/${APP}.desktop"
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "${DESKTOP_DIR}" || true

if [[ "${1:-}" == "--autostart" ]]; then
    echo "Enabling autostart…"
    mkdir -p "${AUTOSTART_DIR}"
    sed 's/^Exec=.*/Exec=lumen --minimized/' "${HERE}/lumen.desktop" > "${AUTOSTART_DIR}/${APP}.desktop"
fi

echo
echo "Installed. Make sure ${BIN} is on your PATH, then run:  lumen"
echo "Note: full gamma ramps require an X11 session. On Wayland, Lumen uses the"
echo "xrandr fallback where available."
