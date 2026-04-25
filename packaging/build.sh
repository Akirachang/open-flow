#!/usr/bin/env bash
# Builds Open Flow.app and packages it into a DMG for distribution.
# Run from the repo root: ./packaging/build.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DIST_DIR="$REPO_ROOT/dist"
APP_NAME="Open Flow"
APP_BUNDLE="$DIST_DIR/$APP_NAME.app"
DMG_PATH="$DIST_DIR/OpenFlow.dmg"

echo "==> Cleaning previous build..."
rm -rf "$DIST_DIR" "$REPO_ROOT/build"

echo "==> Installing PyInstaller..."
uv add pyinstaller --quiet

echo "==> Building .app with PyInstaller..."
cd "$REPO_ROOT"
uv run pyinstaller packaging/OpenFlow.spec \
  --distpath "$DIST_DIR" \
  --workpath "$REPO_ROOT/build" \
  --noconfirm

if [ ! -d "$APP_BUNDLE" ]; then
  echo "ERROR: Build failed — $APP_BUNDLE not found."
  exit 1
fi

echo "==> Build succeeded: $APP_BUNDLE"

# ── DMG creation ────────────────────────────────────────────────────────────
if ! command -v create-dmg &>/dev/null; then
  echo "==> Installing create-dmg..."
  brew install create-dmg
fi

echo "==> Creating DMG..."
rm -f "$DMG_PATH"

create-dmg \
  --volname "$APP_NAME" \
  --window-size 560 340 \
  --icon-size 100 \
  --icon "$APP_NAME.app" 140 170 \
  --hide-extension "$APP_NAME.app" \
  --app-drop-link 420 170 \
  --no-internet-enable \
  "$DMG_PATH" \
  "$APP_BUNDLE"

echo ""
echo "Done! Distributable DMG:"
echo "  $DMG_PATH"
echo ""
echo "Upload this file to a GitHub Release and update install.sh with the download URL."
