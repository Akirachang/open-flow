"""Entry point — Phase 5: full tray app."""

from __future__ import annotations

import logging
import sys

from open_flow.permissions import check_all, open_accessibility_settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)


def main() -> None:
    if not check_all():
        print("\nAccessibility permission is required for text injection.")
        print("Opening System Settings…")
        open_accessibility_settings()
        print("Grant access, then relaunch open-flow.")
        sys.exit(1)

    # Import here so rumps doesn't start until permissions are confirmed
    from open_flow.tray import OpenFlowApp

    OpenFlowApp().run()
