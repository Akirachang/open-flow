"""rumps menu-bar tray app."""

from __future__ import annotations

import logging
import queue
import time
from threading import Thread
from typing import Callable

import rumps

from open_flow import config as cfg_module
from open_flow.audio import AudioRecorder, LAST_WAV
from open_flow.cleanup import Cleaner
from open_flow.hotkey import HotkeyListener
from open_flow.hud import HUD
from open_flow.inject import inject
from open_flow.transcribe import Transcriber

logger = logging.getLogger(__name__)

# Queue drained by a rumps Timer on the main thread
_main_thread_queue: queue.SimpleQueue = queue.SimpleQueue()


def _call_on_main_thread(fn: Callable[[], None]) -> None:
    """Enqueue fn() to be called on the main thread by the drain timer."""
    _main_thread_queue.put(fn)


_ICON_IDLE = "◉"
_ICON_RECORDING = "🔴"
_ICON_PROCESSING = "⏳"
_ICON_ERROR = "⚠️"


class OpenFlowApp(rumps.App):
    def __init__(self) -> None:
        super().__init__(name="Open Flow", title=_ICON_IDLE, quit_button=None)

        self._cfg = cfg_module.load()
        self._recorder = AudioRecorder(
            sample_rate=self._cfg.sample_rate,
            channels=self._cfg.channels,
        )
        self._transcriber = Transcriber(self._cfg)
        self._cleaner: Cleaner | None = None
        self._hotkey: HotkeyListener | None = None
        self._hud = HUD()
        self._start_time: float = 0.0
        self._ready = False

        self._status_item = rumps.MenuItem("Status: Loading…", callback=None)
        self._llm_item = rumps.MenuItem(
            "LLM Cleanup: on" if self._cfg.llm_enabled else "LLM Cleanup: off",
            callback=self._toggle_llm,
        )

        self.menu = [
            rumps.MenuItem("Open Flow", callback=None),
            None,
            self._status_item,
            None,
            self._llm_item,
            None,
            rumps.MenuItem("Preferences…", callback=self._open_prefs),
            rumps.MenuItem("Quit", callback=self._quit),
        ]

        # Drain the main-thread callback queue and tick the HUD at 30 Hz
        self._drain_timer = rumps.Timer(self._drain_and_tick, 1.0 / 30)
        self._drain_timer.start()

        Thread(target=self._load_models, daemon=True).start()

    # ------------------------------------------------------------------ #
    # Startup                                                              #
    # ------------------------------------------------------------------ #

    def _load_models(self) -> None:
        def _ui(title: str, status: str) -> None:
            _call_on_main_thread(lambda: (setattr(self, "title", title), self._set_status(status)))

        try:
            _ui(_ICON_IDLE, "Loading Whisper…")
            self._transcriber.load()

            if self._cfg.llm_enabled:
                _ui(_ICON_IDLE, "Loading LLM…")
                self._cleaner = Cleaner(self._cfg)
                self._cleaner.load()

            self._start_hotkey()
            self._ready = True
            _call_on_main_thread(self._hud.build)
            _ui(_ICON_IDLE, f"Idle — hold {self._cfg.hotkey} to dictate")

        except FileNotFoundError as exc:
            logger.error("Model not found: %s", exc)
            _ui(_ICON_ERROR, "Error: model missing — run download_models.py")
            rumps.notification(
                title="Open Flow",
                subtitle="Model not found",
                message="Run: uv run python scripts/download_models.py",
            )
        except Exception as exc:
            logger.exception("Startup error")
            _ui(_ICON_ERROR, f"Error: {exc}")

    def _start_hotkey(self) -> None:
        self._hotkey = HotkeyListener(
            key_name=self._cfg.hotkey,
            on_press=self._on_press,
            on_release=self._on_release,
        )
        self._hotkey.start()

    # ------------------------------------------------------------------ #
    # Hotkey callbacks                                                     #
    # ------------------------------------------------------------------ #

    def _on_press(self) -> None:
        if not self._ready:
            return
        self._start_time = time.monotonic()
        self._recorder.on_chunk = self._hud.push_audio
        self._recorder.start()

        def _ui() -> None:
            self.title = _ICON_RECORDING
            self._set_status("Recording…")
            self._hud.show()

        _call_on_main_thread(_ui)

    def _on_release(self) -> None:
        if not self._ready:
            return
        self._recorder.on_chunk = None
        audio = self._recorder.stop()
        record_duration = time.monotonic() - self._start_time
        self._recorder.save_wav(audio, LAST_WAV)

        def _ui() -> None:
            self.title = _ICON_PROCESSING
            self._set_status("Transcribing…")
            self._hud.show_loading()

        _call_on_main_thread(_ui)
        Thread(target=self._process, args=(audio, record_duration), daemon=True).start()

    def _process(self, audio, record_duration: float) -> None:
        def _ui(title: str, status: str, hide_hud: bool = False) -> None:
            def _do() -> None:
                setattr(self, "title", title)
                self._set_status(status)
                if hide_hud:
                    self._hud.hide()
            _call_on_main_thread(_do)

        try:
            text = self._transcriber.transcribe(audio, record_duration)

            if not text:
                _ui(_ICON_IDLE, "No speech detected", hide_hud=True)
                return

            if self._cleaner is not None:
                _call_on_main_thread(lambda: self._set_status("Cleaning…"))
                text = self._cleaner.clean(text, record_duration)

            injected = inject(text)
            if not injected:
                rumps.notification(
                    title="Open Flow",
                    subtitle="Skipped",
                    message="Password fields are not supported.",
                )

            total = time.monotonic() - self._start_time
            preview = text[:50] + ("…" if len(text) > 50 else "")
            _ui(_ICON_IDLE, f"Done ({total:.1f}s) — {preview}", hide_hud=True)

        except Exception as exc:
            logger.exception("Processing error")
            _ui(_ICON_ERROR, f"Error: {exc}", hide_hud=True)

    # ------------------------------------------------------------------ #
    # Menu actions                                                         #
    # ------------------------------------------------------------------ #

    def _toggle_llm(self, sender: rumps.MenuItem) -> None:
        self._cfg.llm_enabled = not self._cfg.llm_enabled
        cfg_module.save(self._cfg)
        sender.title = f"LLM Cleanup: {'on' if self._cfg.llm_enabled else 'off'}"

        if self._cfg.llm_enabled and self._cleaner is None:
            try:
                self._cleaner = Cleaner(self._cfg)
                self._set_status("Loading LLM…")
                Thread(target=self._cleaner.load, daemon=True).start()
            except FileNotFoundError:
                rumps.notification(
                    title="Open Flow",
                    subtitle="LLM model missing",
                    message="Run: uv run python scripts/download_models.py",
                )
                self._cfg.llm_enabled = False
                sender.title = "LLM Cleanup: off"

    def _open_prefs(self, _: rumps.MenuItem) -> None:
        window = rumps.Window(
            title="Open Flow — Preferences",
            message="Hotkey (e.g. right_alt, right_ctrl, f13):",
            default_text=self._cfg.hotkey,
            ok="Save",
            cancel="Cancel",
            dimensions=(260, 24),
        )
        response = window.run()
        if response.clicked and response.text.strip():
            new_key = response.text.strip()
            if new_key != self._cfg.hotkey:
                self._cfg.hotkey = new_key
                cfg_module.save(self._cfg)
                if self._hotkey:
                    self._hotkey.stop()
                self._start_hotkey()
                self._set_status(f"Hotkey updated → {new_key}")

    def _quit(self, _: rumps.MenuItem) -> None:
        if self._hotkey:
            self._hotkey.stop()
        self._drain_timer.stop()
        rumps.quit_application()

    # ------------------------------------------------------------------ #
    # Helpers                                                              #
    # ------------------------------------------------------------------ #

    def _drain_and_tick(self, _: rumps.Timer) -> None:
        while not _main_thread_queue.empty():
            try:
                fn = _main_thread_queue.get_nowait()
                fn()
            except Exception:
                logger.exception("Error in main-thread callback")
        self._hud.tick()

    def _set_status(self, message: str) -> None:
        self._status_item.title = f"Status: {message}"
        logger.info("Status: %s", message)
