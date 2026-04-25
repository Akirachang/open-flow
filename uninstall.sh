#!/usr/bin/env bash
# Open Flow uninstaller — run with:
#   curl -fsSL https://raw.githubusercontent.com/Akirachang/open-flow/main/uninstall.sh | bash
set -euo pipefail

APP_NAME="Open Flow"
APP_DEST="/Applications/$APP_NAME.app"
LAUNCH_AGENT="$HOME/Library/LaunchAgents/com.openflow.app.plist"
CONFIG_DIR="$HOME/.config/open_flow"
CACHE_DIR="$HOME/.cache/open_flow"

print_step() { printf "\n\033[1m%s\033[0m\n" "$1"; }
print_ok()   { printf "  \033[32m✓\033[0m  %s\n" "$1"; }
print_skip() { printf "  \033[90m–\033[0m  %s\n" "$1"; }

printf "\n"
printf "  Open Flow — Uninstaller\n"
printf "  ────────────────────────\n"

# ── Quit the running app if it's open ────────────────────────────────────────
print_step "Stopping Open Flow"
if pgrep -x "Open Flow" &>/dev/null; then
  pkill -x "Open Flow" && print_ok "Stopped running app" || true
else
  print_skip "App not running"
fi

# ── Remove LaunchAgent ───────────────────────────────────────────────────────
print_step "Removing login item"
if [ -f "$LAUNCH_AGENT" ]; then
  launchctl unload "$LAUNCH_AGENT" 2>/dev/null || true
  rm "$LAUNCH_AGENT"
  print_ok "Removed LaunchAgent"
else
  print_skip "No LaunchAgent found"
fi

# ── Remove the app bundle ────────────────────────────────────────────────────
print_step "Removing app"
if [ -d "$APP_DEST" ]; then
  rm -rf "$APP_DEST"
  print_ok "Removed $APP_DEST"
else
  print_skip "App not in /Applications"
fi

# ── Optionally remove user data ───────────────────────────────────────────────
printf "\n"
printf "  Remove settings and downloaded models?\n"
printf "  (Models are ~3.5 GB — say yes to free the space)\n"
printf "  [y/N] "
read -r ANSWER </dev/tty || ANSWER="n"

if [[ "${ANSWER,,}" == "y" ]]; then
  print_step "Removing user data"
  [ -d "$CONFIG_DIR" ] && rm -rf "$CONFIG_DIR" && print_ok "Removed config ($CONFIG_DIR)" || print_skip "No config dir"
  [ -d "$CACHE_DIR"  ] && rm -rf "$CACHE_DIR"  && print_ok "Removed cache ($CACHE_DIR)"  || print_skip "No cache dir"
else
  print_skip "Keeping settings and models"
fi

printf "\n"
printf "  \033[1mOpen Flow has been uninstalled.\033[0m\n\n"
