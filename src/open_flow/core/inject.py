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
from Quartz import (
    CGEventCreateKeyboardEvent,
    CGEventPost,
    CGEventSetFlags,
    kCGEventFlagMaskCommand,
    kCGHIDEventTap,
)

logger = logging.getLogger(__name__)

# Virtual key code for 'v'
_KEY_V = 0x09
_PASTE_DELAY = 0.05   # seconds between clipboard set and Cmd+V
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
    src = CGEventCreateKeyboardEvent(None, _KEY_V, True)
    CGEventSetFlags(src, kCGEventFlagMaskCommand)
    CGEventPost(kCGHIDEventTap, src)

    src = CGEventCreateKeyboardEvent(None, _KEY_V, False)
    CGEventSetFlags(src, kCGEventFlagMaskCommand)
    CGEventPost(kCGHIDEventTap, src)


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
