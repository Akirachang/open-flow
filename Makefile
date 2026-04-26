# Open Flow — developer convenience targets.
# Most "tests" for this project are interactive (you have to walk the wizard),
# so this Makefile only covers the scriptable parts: running, building,
# installing, and a couple of post-install sanity checks.

SHELL := /bin/bash

APP_NAME    := Open Flow
APP_BUNDLE  := /Applications/$(APP_NAME).app
CONFIG      := $(HOME)/.config/open_flow/config.toml
LAUNCHAGENT := $(HOME)/Library/LaunchAgents/com.openflow.app.plist
LOG         := $(HOME)/Library/Logs/OpenFlow.log
DMG         := dist/OpenFlow.dmg

.DEFAULT_GOAL := help

.PHONY: help run replay reset build install-local uninstall \
        check-instances check-launchagent check-config tail-log clean

help:  ## List available targets
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

# ── Run from source ─────────────────────────────────────────────────────────

run:  ## Run from source (uv)
	uv run python -m open_flow

reset:  ## Flip onboarding_complete back to false (no app launch)
	@if [ -f "$(CONFIG)" ]; then \
	  sed -i '' 's/onboarding_complete = true/onboarding_complete = false/' "$(CONFIG)"; \
	  echo "Reset onboarding_complete in $(CONFIG)"; \
	else \
	  echo "No config yet at $(CONFIG) — first run will create it."; \
	fi

replay: reset run  ## Reset onboarding then run from source

# ── Build + install the .app ────────────────────────────────────────────────

build:  ## Build .app + DMG via packaging/build.sh
	./packaging/build.sh

install-local: $(DMG)  ## Install the locally-built DMG into /Applications
	./install.sh --local $(DMG)

$(DMG):
	$(MAKE) build

uninstall:  ## Run uninstall.sh
	./uninstall.sh

# ── Post-install sanity checks ──────────────────────────────────────────────

check-instances:  ## Verify only one Open Flow process is running
	@count=$$(pgrep -x "$(APP_NAME)" | wc -l | tr -d ' '); \
	echo "Open Flow processes running: $$count"; \
	pgrep -lx "$(APP_NAME)" || true; \
	if [ "$$count" -gt 1 ]; then echo "FAIL: more than one instance"; exit 1; fi

check-launchagent:  ## Verify plist exists and is NOT eagerly loaded
	@if [ -f "$(LAUNCHAGENT)" ]; then \
	  echo "plist present: $(LAUNCHAGENT)"; \
	else \
	  echo "no plist (only written after first onboarding from /Applications)"; \
	fi
	@loaded=$$(launchctl list | grep -c openflow || true); \
	echo "launchctl entries for openflow: $$loaded"; \
	if [ "$$loaded" -gt 0 ]; then \
	  echo "note: launchd has loaded it (expected after a logout/login cycle)"; \
	fi

check-config:  ## Print the current config
	@if [ -f "$(CONFIG)" ]; then cat "$(CONFIG)"; else echo "no config at $(CONFIG)"; fi

tail-log:  ## Tail the installed app's log
	@if [ -f "$(LOG)" ]; then tail -f "$(LOG)"; else echo "no log at $(LOG) — only written by /Applications install"; fi

# ── Cleanup ─────────────────────────────────────────────────────────────────

clean:  ## Remove build/ and dist/
	rm -rf build dist
