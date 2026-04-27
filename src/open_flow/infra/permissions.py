"""macOS permission checks with clear failure messages.

The AX trust check probes a permission-gated read on a *foreign* process
rather than calling AXIsProcessTrusted. The latter is canonical but its
return value is cached in the AX framework for the process lifetime —
a fresh grant made while the wizard is running won't be visible until
the app restarts. The probe below queries another process's AXRole,
which actually requires Accessibility, so it reflects the live TCC state.
"""

from __future__ import annotations

import logging
import os
import subprocess

from AppKit import NSWorkspace
from ApplicationServices import (
    AXUIElementCopyAttributeValue,
    AXUIElementCreateApplication,
)

logger = logging.getLogger(__name__)


def _foreign_pid() -> int | None:
    """Pid of a stable foreign GUI app to probe.

    The probe attribute (AXWindows) only behaves as a TCC gate when the
    target is a real "regular" GUI application — system services and
    accessory apps may return success without requiring AX trust, which
    would give us a false positive.

    Strategy:
    1. Prefer Finder — it's always running, owned by the user, has at least
       one window (the desktop), and is properly AX-gated.
    2. Fall back to any other regular (activationPolicy == Regular) foreign
       GUI app if Finder is somehow missing.
    """
    my_pid = os.getpid()
    apps = NSWorkspace.sharedWorkspace().runningApplications()

    for app in apps:
        if app.bundleIdentifier() == "com.apple.finder":
            try:
                pid = int(app.processIdentifier())
            except Exception:
                continue
            if pid > 0 and pid != my_pid:
                return pid

    for app in apps:
        try:
            pid = int(app.processIdentifier())
        except Exception:
            continue
        if pid <= 0 or pid == my_pid:
            continue
        if not app.isFinishedLaunching():
            continue
        # NSApplicationActivationPolicyRegular = 0 — only "real" GUI apps.
        # Accessory (1, menu-bar apps like ours) and Prohibited (2, background)
        # are not reliably AX-gated.
        try:
            if int(app.activationPolicy()) != 0:
                continue
        except Exception:
            continue
        return pid

    return None


def check_accessibility() -> bool:
    """Live AX trust check via a permission-gated foreign-process read.

    We query AXWindows of a foreign GUI app. Enumerating another process's
    windows is gated by Accessibility — without trust, the call returns
    kAXErrorCannotComplete or kAXErrorAPIDisabled. AXRole would NOT work
    here: it returns the constant "AXApplication" without requiring trust,
    so it always succeeds and produces false positives.
    """
    pid = _foreign_pid()
    if pid is None:
        logger.info("AX probe: no foreign GUI process available — reporting denied")
        return False
    ax_app = AXUIElementCreateApplication(pid)
    err, _ = AXUIElementCopyAttributeValue(ax_app, "AXWindows", None)
    granted = int(err) == 0
    # Logged at INFO so we can confirm the probe is actually firing and what
    # it's seeing. Quiet enough that it won't drown the log; loud enough that
    # we don't have to hunt for it when the wizard misbehaves.
    logger.info("AX probe: pid=%d err=%s granted=%s", pid, err, granted)
    return granted


def open_accessibility_settings() -> None:
    subprocess.run(
        ["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"],
        check=False,
    )


def check_all() -> bool:
    """Return True only if all required permissions are granted."""
    ok = True
    if not check_accessibility():
        logger.error(
            "Accessibility permission missing.\n"
            "  → System Settings > Privacy & Security > Accessibility\n"
            "     Add Open Flow (or your terminal app, when running from source)."
        )
        ok = False
    # Microphone is checked implicitly by sounddevice on first capture.
    # Input Monitoring is only relevant when an F-key hotkey is configured.
    return ok
