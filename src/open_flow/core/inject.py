"""Text injection via clipboard swap + synthesized Cmd+V."""

from __future__ import annotations

import logging
import time
from threading import Timer

from AppKit import NSPasteboard, NSPasteboardTypeString
from ApplicationServices import (
    AXUIElementCreateSystemWide,
    AXUIElementCopyAttributeValue,
)

from open_flow.infra.permissions import check_accessibility
from Quartz import (
    CGEventCreateKeyboardEvent,
    CGEventPost,
    CGEventSetFlags,
    kCGEventFlagMaskCommand,
    kCGHIDEventTap,
)

logger = logging.getLogger(__name__)

# macOS virtual key codes (from <HIToolbox/Events.h>).
_KEY_V = 0x09
_KEY_CMD = 0x37  # left Command

_PASTE_DELAY = 0.05    # seconds between clipboard set and Cmd+V
_KEY_DELAY = 0.01      # seconds between consecutive synthesized key events
_RESTORE_DELAY = 0.25  # seconds before restoring original clipboard


def _get_clipboard() -> str:
    pb = NSPasteboard.generalPasteboard()
    text = pb.stringForType_(NSPasteboardTypeString)
    return text or ""


def _set_clipboard(text: str) -> None:
    pb = NSPasteboard.generalPasteboard()
    pb.clearContents()
    pb.setString_forType_(text, NSPasteboardTypeString)


def _send_cmd_v() -> None:
    """Synthesize ⌘V with explicit Cmd-down / Cmd-up around V.

    Setting the Cmd flag on a lone V event is enough for AppKit text fields,
    but Terminal, iTerm, Electron apps, and JetBrains IDEs only recognize
    the shortcut when the modifier has its own keyDown/keyUp pair. Bracketing
    V with real Cmd events makes this look like a genuine keystroke.
    """
    cmd_down = CGEventCreateKeyboardEvent(None, _KEY_CMD, True)
    CGEventPost(kCGHIDEventTap, cmd_down)
    time.sleep(_KEY_DELAY)

    v_down = CGEventCreateKeyboardEvent(None, _KEY_V, True)
    CGEventSetFlags(v_down, kCGEventFlagMaskCommand)
    CGEventPost(kCGHIDEventTap, v_down)
    time.sleep(_KEY_DELAY)

    v_up = CGEventCreateKeyboardEvent(None, _KEY_V, False)
    CGEventSetFlags(v_up, kCGEventFlagMaskCommand)
    CGEventPost(kCGHIDEventTap, v_up)
    time.sleep(_KEY_DELAY)

    cmd_up = CGEventCreateKeyboardEvent(None, _KEY_CMD, False)
    CGEventPost(kCGHIDEventTap, cmd_up)


def _focused_element_is_secure() -> bool:
    try:
        system_el = AXUIElementCreateSystemWide()
        err, focused = AXUIElementCopyAttributeValue(system_el, "AXFocusedUIElement", None)
        if err != 0 or focused is None:
            return False
        err, role = AXUIElementCopyAttributeValue(focused, "AXRole", None)
        if err != 0:
            return False
        return role == "AXSecureTextField"
    except Exception:
        return False


def inject(text: str) -> bool:
    """Inject text into the focused app. Returns False if injection was skipped."""
    if not check_accessibility():
        logger.error(
            "Accessibility permission not granted — synthesized Cmd+V will be "
            "silently dropped. Re-grant in System Settings → Privacy → "
            "Accessibility for this exact build (remove the stale entry first)."
        )
        # Still put the text on the clipboard so the user can paste manually.
        _set_clipboard(text)
        return False

    if _focused_element_is_secure():
        logger.warning("Focused element is a password field — skipping injection")
        return False

    original = _get_clipboard()
    _set_clipboard(text)
    time.sleep(_PASTE_DELAY)
    _send_cmd_v()
    logger.info("Injected %d chars", len(text))

    def _restore() -> None:
        _set_clipboard(original)
        logger.debug("Clipboard restored")

    Timer(_RESTORE_DELAY, _restore).start()
    return True
