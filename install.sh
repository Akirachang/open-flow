#!/usr/bin/env bash
# Open Flow installer — run with:
#   curl -fsSL https://raw.githubusercontent.com/YOUR_USERNAME/open-flow/main/install.sh | bash
#
# Local testing (after running ./packaging/build.sh):
#   ./install.sh --local dist/OpenFlow.dmg
set -euo pipefail

APP_NAME="Open Flow"
APP_DEST="/Applications/$APP_NAME.app"
# ── UPDATE THESE when you upload a new GitHub Release ─────────────────────
DMG_URL="https://github.com/YOUR_USERNAME/open-flow/releases/latest/download/OpenFlow.dmg"
SHA_URL="https://github.com/YOUR_USERNAME/open-flow/releases/latest/download/OpenFlow.dmg.sha256"
# ──────────────────────────────────────────────────────────────────────────

TMP_DIR="$(mktemp -d)"
DMG_PATH="$TMP_DIR/OpenFlow.dmg"
MOUNT_POINT="$TMP_DIR/mount"

cleanup() { rm -rf "$TMP_DIR"; }
trap cleanup EXIT

# ── Helpers ──────────────────────────────────────────────────────────────────
print_step() { printf "\n\033[1m%s\033[0m\n" "$1"; }
print_ok()   { printf "  \033[32m✓\033[0m  %s\n" "$1"; }
print_err()  { printf "  \033[31m✗\033[0m  %s\n" "$1" >&2; }

spinner() {
  local pid=$1 msg=$2
  local frames=("⠋" "⠙" "⠹" "⠸" "⠼" "⠴" "⠦" "⠧" "⠇" "⠏")
  local i=0
  while kill -0 "$pid" 2>/dev/null; do
    printf "\r  %s  %s" "${frames[$((i % ${#frames[@]}))]}" "$msg"
    sleep 0.1
    ((i++)) || true
  done
  printf "\r"
}

# ── Checks ──────────────────────────────────────────────────────────────────
if [[ "$(uname)" != "Darwin" ]]; then
  print_err "Open Flow is macOS only."
  exit 1
fi

OS_MAJOR=$(sw_vers -productVersion | cut -d. -f1)
if [[ "$OS_MAJOR" -lt 13 ]]; then
  print_err "Open Flow requires macOS 13 (Ventura) or later. You have: $(sw_vers -productVersion)"
  exit 1
fi

printf "\n"
printf "  Open Flow — Installer\n"
printf "  ─────────────────────\n"

# ── Download (or use local file) ─────────────────────────────────────────────
if [[ "${1:-}" == "--local" ]]; then
  LOCAL_DMG="${2:-dist/OpenFlow.dmg}"
  print_step "Using local build"
  cp "$LOCAL_DMG" "$DMG_PATH"
  print_ok "Loaded $LOCAL_DMG"
else
  print_step "Downloading Open Flow"
  (curl -fsSL --progress-bar "$DMG_URL" -o "$DMG_PATH") &
  spinner $! "Downloading…"
  wait $!
  print_ok "Downloaded"

  # Verify checksum if the .sha256 file is available
  if curl -fsSL "$SHA_URL" -o "$TMP_DIR/OpenFlow.dmg.sha256" 2>/dev/null; then
    print_step "Verifying download"
    EXPECTED=$(awk '{print $1}' "$TMP_DIR/OpenFlow.dmg.sha256")
    ACTUAL=$(shasum -a 256 "$DMG_PATH" | awk '{print $1}')
    if [[ "$EXPECTED" != "$ACTUAL" ]]; then
      print_err "Checksum mismatch — download may be corrupt. Please try again."
      exit 1
    fi
    print_ok "Checksum verified"
  fi
fi

# ── Mount DMG ────────────────────────────────────────────────────────────────
print_step "Installing"
mkdir -p "$MOUNT_POINT"
hdiutil attach "$DMG_PATH" -mountpoint "$MOUNT_POINT" -nobrowse -quiet

# ── Copy .app ────────────────────────────────────────────────────────────────
if [ -d "$APP_DEST" ]; then
  rm -rf "$APP_DEST"
fi

cp -R "$MOUNT_POINT/$APP_NAME.app" "/Applications/"
hdiutil detach "$MOUNT_POINT" -quiet
print_ok "Copied to /Applications"

# ── Remove quarantine flag ────────────────────────────────────────────────────
xattr -dr com.apple.quarantine "$APP_DEST" 2>/dev/null || true
print_ok "Cleared security quarantine"

# ── Launch ───────────────────────────────────────────────────────────────────
print_step "Launching Open Flow"
open "$APP_DEST"

printf "\n"
printf "  \033[1mOpen Flow is installed!\033[0m\n"
printf "\n"
printf "  Look for the  ◉  icon in your menu bar.\n"
printf "  The setup wizard will guide you through the first-run steps.\n"
printf "\n"
printf "  To uninstall later:\n"
printf "    curl -fsSL https://raw.githubusercontent.com/YOUR_USERNAME/open-flow/main/uninstall.sh | bash\n"
printf "\n"
