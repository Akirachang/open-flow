#!/usr/bin/env bash
# Builds Open Flow.app and packages it into a DMG for distribution.
# Run from the repo root: ./packaging/build.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PACKAGING="$REPO_ROOT/packaging"
DIST_DIR="$REPO_ROOT/dist"
APP_NAME="Open Flow"
APP_BUNDLE="$DIST_DIR/$APP_NAME.app"
DMG_PATH="$DIST_DIR/OpenFlow.dmg"
ICON="$PACKAGING/OpenFlow.icns"

echo "==> Cleaning previous build..."
rm -rf "$DIST_DIR" "$REPO_ROOT/build"

# ── Generate icon (always, so changes to make_icon.py take effect) ───────────
cd "$REPO_ROOT"
echo "==> Generating icon..."
uv run python packaging/make_icon.py

# ── Build the .app ───────────────────────────────────────────────────────────
# PyInstaller is pinned in pyproject.toml; `uv run` resolves it from the
# project env, no separate `uv add` step needed (which would mutate the lock).
echo "==> Building .app with PyInstaller..."
uv run pyinstaller packaging/OpenFlow.spec \
  --distpath "$DIST_DIR" \
  --workpath "$REPO_ROOT/build" \
  --noconfirm

if [ ! -d "$APP_BUNDLE" ]; then
  echo "ERROR: Build failed — $APP_BUNDLE not found."
  exit 1
fi

echo "==> Build succeeded: $APP_BUNDLE"

# ── Ad-hoc code-sign ────────────────────────────────────────────────────────
# Without a signature TCC won't keep an Input Monitoring / Accessibility
# entry for the app — every rebuild looks like a brand-new binary and the
# grant silently disappears. An ad-hoc signature (`-` identity) is enough
# to give TCC a stable anchor; we're not Apple-notarizing yet.
echo "==> Ad-hoc code-signing the bundle..."
codesign --force --deep --sign - "$APP_BUNDLE"
codesign --verify --verbose=2 "$APP_BUNDLE" || {
  echo "ERROR: codesign verification failed."
  exit 1
}

# ── DMG creation ────────────────────────────────────────────────────────────
if ! command -v create-dmg &>/dev/null; then
  echo "==> Installing create-dmg..."
  brew install create-dmg
fi

echo "==> Creating DMG..."
rm -f "$DMG_PATH"

ICON_FLAG=""
[ -f "$ICON" ] && ICON_FLAG="--volicon $ICON"

create-dmg \
  --volname "$APP_NAME" \
  $ICON_FLAG \
  --window-size 560 340 \
  --icon-size 100 \
  --icon "$APP_NAME.app" 140 170 \
  --hide-extension "$APP_NAME.app" \
  --app-drop-link 420 170 \
  --no-internet-enable \
  "$DMG_PATH" \
  "$APP_BUNDLE"

# ── Checksum ─────────────────────────────────────────────────────────────────
echo "==> Generating checksum..."
cd "$DIST_DIR"
shasum -a 256 OpenFlow.dmg > OpenFlow.dmg.sha256
echo "    $(cat OpenFlow.dmg.sha256)"

echo ""
echo "Done! Distributable files:"
echo "  $DMG_PATH"
echo "  ${DMG_PATH}.sha256"
echo ""
echo "Next: create a GitHub Release tagged v<version> and upload both files."
echo "      Then update YOUR_USERNAME in install.sh, uninstall.sh, and tray.py."
