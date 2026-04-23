"""Global push-to-talk hotkey listener via pynput."""

from __future__ import annotations

import logging
from threading import Thread
from typing import Callable

from pynput import keyboard

logger = logging.getLogger(__name__)

# Map config string → pynput Key
_KEY_MAP: dict[str, keyboard.Key] = {
    "right_alt": keyboard.Key.alt_r,
    "right_ctrl": keyboard.Key.ctrl_r,
    "right_shift": keyboard.Key.shift_r,
    "left_alt": keyboard.Key.alt_l,
    "left_ctrl": keyboard.Key.ctrl_l,
    "caps_lock": keyboard.Key.caps_lock,
    "f13": keyboard.Key.f13,
    "f14": keyboard.Key.f14,
    "f15": keyboard.Key.f15,
}


class HotkeyListener:
    def __init__(
        self,
        key_name: str,
        on_press: Callable[[], None],
        on_release: Callable[[], None],
    ) -> None:
        self._key = _KEY_MAP.get(key_name, keyboard.Key.alt_r)
        self._on_press = on_press
        self._on_release = on_release
        self._held = False
        self._listener: keyboard.Listener | None = None

    def _handle_press(self, key: keyboard.Key | keyboard.KeyCode) -> None:
        if key == self._key and not self._held:
            self._held = True
            logger.debug("Hotkey pressed")
            self._on_press()

    def _handle_release(self, key: keyboard.Key | keyboard.KeyCode) -> None:
        if key == self._key and self._held:
            self._held = False
            logger.debug("Hotkey released")
            self._on_release()

    def start(self) -> None:
        self._listener = keyboard.Listener(
            on_press=self._handle_press,
            on_release=self._handle_release,
        )
        self._listener.start()
        logger.info("Hotkey listener started (key=%s)", self._key)

    def stop(self) -> None:
        if self._listener:
            self._listener.stop()
            self._listener = None
