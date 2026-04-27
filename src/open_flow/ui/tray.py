"""rumps menu-bar tray app."""

from __future__ import annotations

import logging
import queue
import time
import urllib.request
import urllib.error
from pathlib import Path
from threading import Thread
from typing import Callable

# ── Update check ─────────────────────────────────────────────────────────────
# Replace Akirachang with your GitHub username once the repo is public.
_GITHUB_RELEASES_URL = (
    "https://api.github.com/repos/Akirachang/open-flow/releases/latest"
)
_CURRENT_VERSION = "0.1.0"

import rumps

from open_flow.core.audio import AudioRecorder, LAST_WAV
from open_flow.core.cleanup import Cleaner
from open_flow.core.hotkey import HotkeyListener
from open_flow.core.pipeline import DictationPipeline, PipelineResult
from open_flow.core.transcribe import Transcriber
from open_flow.data import config as cfg_module
from open_flow.ui.hud import HUD

logger = logging.getLogger(__name__)

# Queue drained by a rumps Timer on the main thread
_main_thread_queue: queue.SimpleQueue = queue.SimpleQueue()


def _call_on_main_thread(fn: Callable[[], None]) -> None:
    """Enqueue fn() to be called on the main thread by the drain timer."""
    _main_thread_queue.put(fn)


# Menu-bar state is conveyed by a small text suffix next to the waveform icon.
# The icon itself is always the same template waveform that appears as the
# app's Dock / Finder icon, so the brand stays consistent.
_TITLE_IDLE = ""
_TITLE_RECORDING = " ●"
_TITLE_PROCESSING = " …"
_TITLE_ERROR = " !"


def _menubar_icon_path() -> str:
    """Return path to the template waveform PNG, generating it if missing.

    Drawn with the same proportions as the app icon (`packaging/make_icon.py`)
    but on a transparent background so macOS can render it as a template
    image — auto-tinted for light/dark menu bars.
    """
    cache_dir = Path.home() / "Library" / "Caches" / "open_flow"
    cache_dir.mkdir(parents=True, exist_ok=True)
    out = cache_dir / "menubar_template.png"
    if out.exists():
        return str(out)

    from AppKit import (
        NSBezierPath,
        NSBitmapImageRep,
        NSColor,
        NSImage,
        NSMakeRect,
        NSPNGFileType,
    )

    size = 44  # 22pt @2x — matches macOS menu-bar template recommendation
    img = NSImage.alloc().initWithSize_((size, size))
    img.lockFocus()

    NSColor.blackColor().setFill()
    heights = [0.40, 0.65, 0.85, 0.65, 0.40]
    bar_w = size * 0.10
    gap = size * 0.07
    total_w = len(heights) * bar_w + (len(heights) - 1) * gap
    x0 = (size - total_w) / 2
    for i, h in enumerate(heights):
        bh = size * h
        bx = x0 + i * (bar_w + gap)
        by = (size - bh) / 2
        NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            NSMakeRect(bx, by, bar_w, bh), bar_w / 2, bar_w / 2
        ).fill()

    img.unlockFocus()

    rep = NSBitmapImageRep.imageRepWithData_(img.TIFFRepresentation())
    rep.representationUsingType_properties_(NSPNGFileType, None).writeToFile_atomically_(
        str(out), True
    )
    return str(out)


class OpenFlowApp(rumps.App):
    def __init__(self) -> None:
        super().__init__(
            name="Open Flow",
            title=_TITLE_IDLE,
            icon=_menubar_icon_path(),
            template=True,
            quit_button=None,
        )

        self._cfg = cfg_module.load()
        self._recorder = AudioRecorder(
            sample_rate=self._cfg.sample_rate,
            channels=self._cfg.channels,
        )
        self._transcriber = Transcriber(self._cfg)
        self._cleaner: Cleaner | None = None
        self._pipeline = DictationPipeline(self._transcriber, cleaner=None)
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
        Thread(target=self._check_for_update, daemon=True).start()

    # ------------------------------------------------------------------ #
    # Startup                                                              #
    # ------------------------------------------------------------------ #

    def _load_models(self) -> None:
        def _ui(title: str, status: str) -> None:
            _call_on_main_thread(lambda: (setattr(self, "title", title), self._set_status(status)))

        try:
            _ui(_TITLE_IDLE, "Loading Whisper…")
            self._transcriber.load()

            # LLM cleanup is optional. If the model never finished downloading
            # (or the user toggled it off), keep going with transcribe-only —
            # the hotkey + Whisper still work, which is the whole product.
            if self._cfg.llm_enabled:
                _ui(_TITLE_IDLE, "Loading LLM…")
                try:
                    self._cleaner = Cleaner(self._cfg)
                    self._cleaner.load()
                    self._pipeline.set_cleaner(self._cleaner)
                except FileNotFoundError as exc:
                    # The wizard's LLM download likely got interrupted. Kick
                    # off a background re-download so the user gets cleanup
                    # automatically once the network cooperates — no need to
                    # re-walk the wizard.
                    logger.warning("LLM model missing — auto-redownloading: %s", exc)
                    self._cleaner = None
                    self._pipeline.set_cleaner(None)
                    Thread(
                        target=self._redownload_llm_in_background,
                        daemon=True,
                        name="of-llm-redownload",
                    ).start()
                except Exception:
                    logger.exception("LLM load failed — continuing without cleanup")
                    self._cleaner = None
                    self._pipeline.set_cleaner(None)

            self._start_hotkey()
            self._ready = True
            _call_on_main_thread(self._hud.build)
            _ui(_TITLE_IDLE, f"Idle — hold {self._cfg.hotkey} to dictate")

        except FileNotFoundError as exc:
            logger.error("Whisper model not found: %s", exc)
            _ui(_TITLE_ERROR, "Error: Whisper model missing")
            rumps.notification(
                title="Open Flow",
                subtitle="Speech model not found",
                message="Run: uv run python scripts/download_models.py",
            )
        except Exception as exc:
            logger.exception("Startup error")
            _ui(_TITLE_ERROR, f"Error: {exc}")

    def _redownload_llm_in_background(self) -> None:
        """Re-fetch the missing LLM model and attach the cleaner when done.

        Retries with exponential backoff. Hugging Face resumes partial files,
        so a transient blip during onboarding doesn't cost a full restart.
        """
        from huggingface_hub import hf_hub_download

        repo = "Qwen/Qwen2.5-3B-Instruct-GGUF"
        target = self._cfg.llm_model_path
        target.parent.mkdir(parents=True, exist_ok=True)

        _call_on_main_thread(lambda: self._set_status("Re-downloading cleanup model…"))
        rumps.notification(
            title="Open Flow",
            subtitle="Finishing setup",
            message="Re-downloading the cleanup model in the background — dictation works in the meantime.",
        )

        for attempt in range(1, 4):
            try:
                hf_hub_download(
                    repo_id=repo,
                    filename=target.name,
                    local_dir=str(target.parent),
                )
                logger.info("LLM re-download succeeded on attempt %d", attempt)
                break
            except Exception:
                logger.exception("LLM re-download attempt %d failed", attempt)
                if attempt == 3:
                    _call_on_main_thread(
                        lambda: self._set_status("Cleanup model unavailable — dictation OK")
                    )
                    return
                time.sleep(2 ** attempt)

        # Load the cleaner now that the file is on disk.
        try:
            cleaner = Cleaner(self._cfg)
            cleaner.load()
            self._cleaner = cleaner
            self._pipeline.set_cleaner(cleaner)
            _call_on_main_thread(
                lambda: self._set_status(f"Idle — hold {self._cfg.hotkey} to dictate")
            )
            rumps.notification(
                title="Open Flow",
                subtitle="Cleanup model ready",
                message="LLM cleanup is now active.",
            )
        except Exception:
            logger.exception("LLM load failed after re-download")

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
            self.title = _TITLE_RECORDING
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
            self.title = _TITLE_PROCESSING
            self._set_status("Transcribing…")
            self._hud.show_loading()

        _call_on_main_thread(_ui)
        Thread(target=self._process, args=(audio, record_duration), daemon=True).start()

    def _process(self, audio, record_duration: float) -> None:
        def _status(s: str) -> None:
            _call_on_main_thread(lambda: self._set_status(s))

        result: PipelineResult = self._pipeline.run(
            audio, record_duration, on_status=_status
        )

        self._render_result(result)

    def _render_result(self, result: PipelineResult) -> None:
        def _finish(title: str, status: str) -> None:
            _call_on_main_thread(
                lambda: (setattr(self, "title", title),
                         self._set_status(status),
                         self._hud.hide())
            )

        if result.injected and result.text:
            total = time.monotonic() - self._start_time
            preview = result.text[:50] + ("…" if len(result.text) > 50 else "")
            _finish(_TITLE_IDLE, f"Done ({total:.1f}s) — {preview}")
            return

        reason = result.skipped_reason
        if reason == "no_speech":
            _finish(_TITLE_IDLE, "No speech detected")
        elif reason == "password_field":
            rumps.notification(
                title="Open Flow",
                subtitle="Skipped",
                message="Password fields are not supported.",
            )
            _finish(_TITLE_IDLE, "Skipped password field")
        else:
            _finish(_TITLE_ERROR, f"Error: {result.error or 'unknown'}")

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

                def _load_and_attach() -> None:
                    self._cleaner.load()
                    self._pipeline.set_cleaner(self._cleaner)

                Thread(target=_load_and_attach, daemon=True).start()
            except FileNotFoundError:
                rumps.notification(
                    title="Open Flow",
                    subtitle="LLM model missing",
                    message="Run: uv run python scripts/download_models.py",
                )
                self._cfg.llm_enabled = False
                sender.title = "LLM Cleanup: off"
        elif not self._cfg.llm_enabled:
            self._pipeline.set_cleaner(None)

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
                from open_flow.core.hotkey import is_modifier_hotkey
                self._cfg.hotkey = new_key
                cfg_module.save(self._cfg)
                if self._hotkey:
                    self._hotkey.stop()
                self._start_hotkey()
                self._set_status(f"Hotkey updated → {new_key}")
                # Switching to a non-modifier hotkey (F13/F14/F15) requires
                # Input Monitoring. Nudge the user to grant it now, since the
                # listener will silently receive nothing without it.
                if not is_modifier_hotkey(new_key):
                    rumps.notification(
                        title="Open Flow",
                        subtitle="Grant Input Monitoring",
                        message=(
                            f"{new_key} is not a modifier key, so macOS needs "
                            "Input Monitoring permission for it to work globally."
                        ),
                    )

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

    def _check_for_update(self) -> None:
        """Check GitHub Releases for a newer version. Runs once on startup."""
        if "Akirachang" in _GITHUB_RELEASES_URL:
            return  # placeholder URL — skip until repo is configured
        try:
            req = urllib.request.Request(
                _GITHUB_RELEASES_URL,
                headers={"Accept": "application/vnd.github+json", "User-Agent": "OpenFlow"},
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                import json
                data = json.loads(resp.read())
            latest = data.get("tag_name", "").lstrip("v")
            if latest and latest != _CURRENT_VERSION:
                _call_on_main_thread(
                    lambda: rumps.notification(
                        title="Open Flow",
                        subtitle=f"Version {latest} is available",
                        message="Visit github.com/Akirachang/open-flow/releases to update.",
                    )
                )
        except Exception:
            pass  # silently ignore — update check is best-effort

    def _set_status(self, message: str) -> None:
        self._status_item.title = f"Status: {message}"
        logger.info("Status: %s", message)
