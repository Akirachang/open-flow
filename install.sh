#!/usr/bin/env bash
# Open Flow installer — run with:
#   curl -fsSL https://raw.githubusercontent.com/YOUR_USERNAME/open-flow/main/install.sh | bash
#
# Local testing (after running ./packaging/build.sh):
#   ./install.sh --local dist/OpenFlow.dmg
set -euo pipefail

APP_NAME="Open Flow"
APP_DEST="/Applications/$APP_NAME.app"
# ── UPDATE THIS URL when you upload a new GitHub Release ──────────────────
DMG_URL="https://github.com/YOUR_USERNAME/open-flow/releases/latest/download/OpenFlow.dmg"
# ──────────────────────────────────────────────────────────────────────────

TMP_DIR="$(mktemp -d)"
DMG_PATH="$TMP_DIR/OpenFlow.dmg"
MOUNT_POINT="$TMP_DIR/mount"

cleanup() { rm -rf "$TMP_DIR"; }
trap cleanup EXIT

# ── Checks ──────────────────────────────────────────────────────────────────
if [[ "$(uname)" != "Darwin" ]]; then
  echo "Error: Open Flow is macOS only."
  exit 1
fi

OS_MAJOR=$(sw_vers -productVersion | cut -d. -f1)
if [[ "$OS_MAJOR" -lt 13 ]]; then
  echo "Error: Open Flow requires macOS 13 (Ventura) or later."
  exit 1
fi

# ── Download (or use local file) ─────────────────────────────────────────────
if [[ "${1:-}" == "--local" ]]; then
  LOCAL_DMG="${2:-dist/OpenFlow.dmg}"
  echo "Using local DMG: $LOCAL_DMG"
  cp "$LOCAL_DMG" "$DMG_PATH"
else
  echo "Downloading Open Flow..."
  curl -fsSL --progress-bar "$DMG_URL" -o "$DMG_PATH"
fi

# ── Mount DMG ────────────────────────────────────────────────────────────────
echo "Mounting disk image..."
mkdir -p "$MOUNT_POINT"
hdiutil attach "$DMG_PATH" -mountpoint "$MOUNT_POINT" -nobrowse -quiet

# ── Copy .app ────────────────────────────────────────────────────────────────
if [ -d "$APP_DEST" ]; then
  echo "Removing existing installation..."
  rm -rf "$APP_DEST"
fi

echo "Installing $APP_NAME to /Applications..."
cp -R "$MOUNT_POINT/$APP_NAME.app" "/Applications/"

# ── Detach DMG ───────────────────────────────────────────────────────────────
hdiutil detach "$MOUNT_POINT" -quiet

# ── Remove quarantine flag (bypasses Gatekeeper for unsigned apps) ───────────
echo "Removing quarantine flag..."
xattr -dr com.apple.quarantine "$APP_DEST" 2>/dev/null || true

# ── Launch ───────────────────────────────────────────────────────────────────
echo ""
echo "Open Flow installed successfully!"
echo "Launching..."
open "$APP_DEST"
