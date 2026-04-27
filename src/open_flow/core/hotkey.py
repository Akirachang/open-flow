"""Global push-to-talk hotkey listener.

Two backends, picked by hotkey name:

* **Modifier keys** (Right Option, Right Ctrl, Right Shift, Caps Lock, …)
  — NSEvent ``flagsChanged`` global monitor. Does **not** require Input
  Monitoring, because modifier-flag changes don't reveal keystrokes.
* **Real keys** (F13/F14/F15) — falls back to ``pynput``'s CGEventTap,
  which **does** require Input Monitoring.

So picking a modifier hotkey lets us ship without requesting that grant.
"""

from __future__ import annotations

import logging
from typing import Callable

logger = logging.getLogger(__name__)


# Device-dependent modifier flag bits, from <IOKit/hidsystem/IOLLEvent.h>.
# These bits sit alongside the device-independent NSEventModifierFlag* bits
# inside NSEvent.modifierFlags(), letting us distinguish left vs right.
_MODIFIER_FLAGS: dict[str, int] = {
    "right_alt":   0x00000040,  # NX_DEVICERALTKEYMASK  (Right Option)
    "left_alt":    0x00000020,  # NX_DEVICELALTKEYMASK
    "right_ctrl":  0x00002000,  # NX_DEVICERCTLKEYMASK
    "left_ctrl":   0x00000001,  # NX_DEVICELCTLKEYMASK
    "right_shift": 0x00000004,  # NX_DEVICERSHIFTKEYMASK
    "caps_lock":   1 << 16,     # NSEventModifierFlagCapsLock
}


def is_modifier_hotkey(key_name: str) -> bool:
    """True if the hotkey can be detected without Input Monitoring."""
    return key_name in _MODIFIER_FLAGS


class _NSEventModifierListener:
    """Detect a modifier key being held via NSEvent flagsChanged events.

    Both global and local monitors are installed: the global monitor fires
    when other apps are active (the common case for a menu-bar app), the
    local one when our own window is key (the wizard's hotkey demo).
    """

    def __init__(
        self,
        key_name: str,
        on_press: Callable[[], None],
        on_release: Callable[[], None],
    ) -> None:
        self._mask = _MODIFIER_FLAGS[key_name]
        self._key_name = key_name
        self._on_press = on_press
        self._on_release = on_release
        self._held = False
        self._global_monitor = None
        self._local_monitor = None

    def start(self) -> None:
        from AppKit import NSEvent

        # NSEventMaskFlagsChanged = 1 << NSEventTypeFlagsChanged (= 12).
        flags_changed_mask = 1 << 12

        def handle(event) -> None:
            try:
                flags = int(event.modifierFlags())
            except Exception:
                return
            now_held = bool(flags & self._mask)
            if now_held and not self._held:
                self._held = True
                logger.debug("Hotkey pressed (%s)", self._key_name)
                try:
                    self._on_press()
                except Exception:
                    logger.exception("on_press callback failed")
            elif not now_held and self._held:
                self._held = False
                logger.debug("Hotkey released (%s)", self._key_name)
                try:
                    self._on_release()
                except Exception:
                    logger.exception("on_release callback failed")

        def local_handler(event):
            handle(event)
            # Returning the event lets normal processing continue.
            return event

        self._global_monitor = (
            NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(
                flags_changed_mask, handle
            )
        )
        self._local_monitor = (
            NSEvent.addLocalMonitorForEventsMatchingMask_handler_(
                flags_changed_mask, local_handler
            )
        )
        logger.info(
            "Hotkey listener started (NSEvent flagsChanged, key=%s, mask=0x%x)",
            self._key_name, self._mask,
        )

    def stop(self) -> None:
        from AppKit import NSEvent
        if self._global_monitor is not None:
            NSEvent.removeMonitor_(self._global_monitor)
            self._global_monitor = None
        if self._local_monitor is not None:
            NSEvent.removeMonitor_(self._local_monitor)
            self._local_monitor = None


class _PynputListener:
    """Fallback CGEventTap listener for F-key hotkeys.

    F13/F14/F15 fire keyDown/keyUp events, not flagsChanged, so we have to
    use a CGEventTap — which means the user must grant Input Monitoring.
    """

    def __init__(
        self,
        key_name: str,
        on_press: Callable[[], None],
        on_release: Callable[[], None],
    ) -> None:
        from pynput import keyboard
        key_map = {
            "f13": keyboard.Key.f13,
            "f14": keyboard.Key.f14,
            "f15": keyboard.Key.f15,
        }
        self._key = key_map.get(key_name, keyboard.Key.f13)
        self._key_name = key_name
        self._on_press = on_press
        self._on_release = on_release
        self._held = False
        self._listener = None

    def _handle_press(self, key) -> None:
        if key == self._key and not self._held:
            self._held = True
            logger.debug("Hotkey pressed (%s)", self._key_name)
            self._on_press()

    def _handle_release(self, key) -> None:
        if key == self._key and self._held:
            self._held = False
            logger.debug("Hotkey released (%s)", self._key_name)
            self._on_release()

    def start(self) -> None:
        from pynput import keyboard
        self._listener = keyboard.Listener(
            on_press=self._handle_press,
            on_release=self._handle_release,
        )
        self._listener.start()
        logger.info(
            "Hotkey listener started (pynput, key=%s — requires Input Monitoring)",
            self._key_name,
        )

    def stop(self) -> None:
        if self._listener:
            self._listener.stop()
            self._listener = None


class HotkeyListener:
    """Dispatcher: picks NSEvent backend for modifiers, pynput for F-keys."""

    def __init__(
        self,
        key_name: str,
        on_press: Callable[[], None],
        on_release: Callable[[], None],
    ) -> None:
        if is_modifier_hotkey(key_name):
            self._impl = _NSEventModifierListener(key_name, on_press, on_release)
        else:
            self._impl = _PynputListener(key_name, on_press, on_release)

    def start(self) -> None:
        self._impl.start()

    def stop(self) -> None:
        self._impl.stop()
