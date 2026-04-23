"""macOS permission checks with clear failure messages."""

from __future__ import annotations

import logging
import subprocess

from ApplicationServices import AXIsProcessTrusted

logger = logging.getLogger(__name__)


def check_accessibility() -> bool:
    trusted = AXIsProcessTrusted()
    if not trusted:
        logger.error(
            "Accessibility permission missing.\n"
            "  → System Settings > Privacy & Security > Accessibility\n"
            "     Add your terminal app, then relaunch open-flow."
        )
    return trusted


def open_accessibility_settings() -> None:
    subprocess.run(
        ["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"],
        check=False,
    )


def check_all() -> bool:
    """Return True only if all required permissions are granted."""
    ok = True
    if not check_accessibility():
        ok = False
    # Microphone is checked implicitly by sounddevice on first capture.
    # Input Monitoring is checked implicitly by pynput on first key event.
    return ok
