#!/usr/bin/env bash
#
# Lumen — macOS app + DMG build (run on macOS).
#
#   1. builds lumen.icns from the generated iconset
#   2. runs PyInstaller to produce dist/Lumen.app
#   3. packages a distributable DMG
#
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "${HERE}/../.." && pwd)"
ASSETS="${ROOT}/lumen/assets"

cd "${ROOT}"

echo "Generating icons…"
python3 scripts/make_icons.py

if [[ -d "${ASSETS}/lumen.iconset" ]]; then
    echo "Building lumen.icns…"
    iconutil -c icns "${ASSETS}/lumen.iconset" -o "${ASSETS}/lumen.icns"
fi

echo "Building app bundle…"
python3 scripts/build.py

APP="dist/Lumen.app"
if [[ ! -d "${APP}" ]]; then
    # --onefile produced a bare binary; wrap is not needed, but prefer .app
    echo "Note: expected ${APP}. If only dist/Lumen exists, re-run build with --windowed bundle."
fi

echo "Creating DMG…"
DMG="dist/Lumen.dmg"
rm -f "${DMG}"
hdiutil create -volname "Lumen" -srcfolder "dist/Lumen.app" -ov -format UDZO "${DMG}" || \
    echo "DMG step skipped (no .app bundle)."

echo "Done. Artifacts in dist/."
echo "Tip: drag Lumen.app to /Applications. Autostart is managed from the app's Settings."
