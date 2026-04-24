"""Step-by-step onboarding wizard — shown on first run only."""

from __future__ import annotations

import logging
import subprocess
import threading
from typing import Callable

import objc
from AppKit import (
    NSBackingStoreBuffered,
    NSBezelStyleRounded,
    NSButton,
    NSCenterTextAlignment,
    NSColor,
    NSFont,
    NSLeftTextAlignment,
    NSMakeRect,
    NSMomentaryLightButton,
    NSProgressIndicator,
    NSScreen,
    NSTextField,
    NSView,
    NSWindow,
    NSWindowStyleMaskClosable,
    NSWindowStyleMaskTitled,
    NSApplication,
)
from Foundation import NSObject

logger = logging.getLogger(__name__)


def _open_privacy_pane(pane: str) -> None:
    """Open a specific Privacy & Security pane in System Settings.

    Uses Popen so the button handler returns immediately — blocking calls
    freeze the UI thread and make the button appear stuck.
    """
    url = f"x-apple.systempreferences:com.apple.preference.security?{pane}"
    logger.info("Opening privacy pane: %s", pane)
    try:
        subprocess.Popen(
            ["open", url],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as exc:
        logger.error("Failed to open privacy pane %s: %s", pane, exc)


_W = 520
_H = 440
_PADDING = 40


# ------------------------------------------------------------------ #
# Single module-level delegate class — avoids PyObjC class redefinition
# ------------------------------------------------------------------ #

class _ButtonDelegate(NSObject):
    def initWithCallbacks_(self, callbacks: dict) -> "_ButtonDelegate":
        self = objc.super(_ButtonDelegate, self).init()
        self._callbacks = callbacks
        return self

    def handleButton_(self, sender: NSButton) -> None:
        tag = sender.tag()
        fn = self._callbacks.get(tag)
        if fn:
            fn()


# ------------------------------------------------------------------ #
# Helpers
# ------------------------------------------------------------------ #

def _label(text: str, x: float, y: float, w: float, h: float,
           size: float = 13, bold: bool = False,
           color: NSColor | None = None,
           align: int = NSCenterTextAlignment) -> NSTextField:
    f = NSTextField.alloc().initWithFrame_(NSMakeRect(x, y, w, h))
    f.setStringValue_(text)
    f.setBezeled_(False)
    f.setDrawsBackground_(False)
    f.setEditable_(False)
    f.setSelectable_(False)
    f.setAlignment_(align)
    f.setFont_(NSFont.boldSystemFontOfSize_(size) if bold else NSFont.systemFontOfSize_(size))
    f.setTextColor_(color or NSColor.labelColor())
    return f


# ------------------------------------------------------------------ #
# Wizard
# ------------------------------------------------------------------ #

class OnboardingWizard:
    STEPS = ["welcome", "permissions", "models", "hotkey"]

    def __init__(self, cfg, on_complete: Callable[[], None]) -> None:
        self._cfg = cfg
        self._on_complete = on_complete
        self._step_index = 0
        self._window: NSWindow | None = None
        self._delegate: _ButtonDelegate | None = None
        self._callbacks: dict[int, Callable[[], None]] = {}
        self._btn_tag = 0
        self._progress_bars: list[NSProgressIndicator] = []
        self._status_labels: list[NSTextField] = []
        self._next_btn: NSButton | None = None
        self._download_btn: NSButton | None = None

    # ------------------------------------------------------------------ #
    # Public                                                               #
    # ------------------------------------------------------------------ #

    def run(self) -> None:
        self._build_window()
        self._show_step(0)
        self._window.makeKeyAndOrderFront_(None)
        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)

    # ------------------------------------------------------------------ #
    # Internal — window + step management                                 #
    # ------------------------------------------------------------------ #

    def _build_window(self) -> None:
        screen = NSScreen.mainScreen()
        sf = screen.frame()
        x = (sf.size.width - _W) / 2
        y = (sf.size.height - _H) / 2

        self._window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(x, y, _W, _H),
            NSWindowStyleMaskTitled | NSWindowStyleMaskClosable,
            NSBackingStoreBuffered,
            False,
        )
        self._window.setTitle_("Welcome to Open Flow")
        self._window.setReleasedWhenClosed_(False)

        # One shared delegate for all button callbacks
        self._callbacks = {}
        self._delegate = _ButtonDelegate.alloc().initWithCallbacks_(self._callbacks)

    def _clear(self) -> None:
        for sub in list(self._window.contentView().subviews()):
            sub.removeFromSuperview()
        self._callbacks.clear()
        self._btn_tag = 0

    def _show_step(self, index: int) -> None:
        self._step_index = index
        self._clear()
        getattr(self, f"_step_{self.STEPS[index]}")()

    def _next(self) -> None:
        if self._step_index + 1 < len(self.STEPS):
            self._show_step(self._step_index + 1)
        else:
            self._finish()

    def _back(self) -> None:
        if self._step_index > 0:
            self._show_step(self._step_index - 1)

    def _add(self, view: NSView) -> NSView:
        self._window.contentView().addSubview_(view)
        return view

    def _btn(self, title: str, x: float, y: float, w: float, h: float,
             action: Callable[[], None]) -> NSButton:
        tag = self._btn_tag
        self._btn_tag += 1
        self._callbacks[tag] = action

        btn = NSButton.alloc().initWithFrame_(NSMakeRect(x, y, w, h))
        btn.setTitle_(title)
        btn.setBezelStyle_(NSBezelStyleRounded)
        btn.setButtonType_(NSMomentaryLightButton)
        btn.setTag_(tag)
        btn.setTarget_(self._delegate)
        btn.setAction_("handleButton:")
        return btn

    # ------------------------------------------------------------------ #
    # Step: Welcome                                                        #
    # ------------------------------------------------------------------ #

    def _step_welcome(self) -> None:
        cx = _W / 2
        self._add(_label("🎙️", cx - 36, _H - 110, 72, 72, size=52))
        self._add(_label("Open Flow", cx - 160, _H - 160, 320, 40,
                         size=28, bold=True))
        self._add(_label(
            "Offline push-to-talk voice dictation for macOS.\n"
            "Hold a hotkey, speak, release — text appears wherever your cursor is.",
            _PADDING, _H - 240, _W - _PADDING * 2, 60, size=14,
        ))
        self._add(_label(
            "Everything runs locally on your Mac.\nNo cloud. No subscription. No data leaves your machine.",
            _PADDING, _H - 310, _W - _PADDING * 2, 50, size=13,
            color=NSColor.secondaryLabelColor(),
        ))
        self._add(self._btn("Get Started →", _W - 180 - _PADDING, 24, 180, 32, self._next))

    # ------------------------------------------------------------------ #
    # Step: Permissions                                                    #
    # ------------------------------------------------------------------ #

    def _step_permissions(self) -> None:
        self._add(_label("Permissions", _PADDING, _H - 65,
                         _W - _PADDING * 2, 34, size=22, bold=True,
                         align=NSLeftTextAlignment))
        self._add(_label(
            "Open Flow needs three permissions. Click each button,\ngrant access in System Settings, then return here.",
            _PADDING, _H - 115, _W - _PADDING * 2, 40, size=13,
            align=NSLeftTextAlignment, color=NSColor.secondaryLabelColor(),
        ))

        perms = [
            ("🎙️  Microphone",
             "Record your voice",
             "Privacy_Microphone"),
            ("⌨️  Input Monitoring",
             "Global hotkey detection",
             "Privacy_ListenEvent"),
            ("♿  Accessibility",
             "Inject text into other apps",
             "Privacy_Accessibility"),
        ]

        for i, (title, desc, pane) in enumerate(perms):
            row_y = _H - 185 - i * 68
            self._add(_label(title, _PADDING, row_y + 18, 260, 20,
                             size=13, bold=True, align=NSLeftTextAlignment))
            self._add(_label(desc, _PADDING, row_y, 260, 16,
                             size=11, align=NSLeftTextAlignment,
                             color=NSColor.secondaryLabelColor()))
            captured = pane
            self._add(self._btn("Open Settings", _W - _PADDING - 130, row_y + 8, 130, 26,
                                lambda p=captured: _open_privacy_pane(p)))

        self._add(self._btn("← Back", _PADDING, 24, 100, 32, self._back))
        self._add(self._btn("Continue →", _W - 180 - _PADDING, 24, 180, 32, self._next))

    # ------------------------------------------------------------------ #
    # Step: Models                                                         #
    # ------------------------------------------------------------------ #

    def _step_models(self) -> None:
        self._progress_bars = []
        self._status_labels = []

        self._add(_label("Download Models", _PADDING, _H - 65,
                         _W - _PADDING * 2, 34, size=22, bold=True,
                         align=NSLeftTextAlignment))
        self._add(_label(
            "Two local AI models are needed (~3.5 GB total).\nDownloaded once, stored on your Mac.",
            _PADDING, _H - 115, _W - _PADDING * 2, 40, size=13,
            align=NSLeftTextAlignment, color=NSColor.secondaryLabelColor(),
        ))

        models = [
            ("Whisper distil-large-v3", "~1.5 GB  ·  speech-to-text",
             self._cfg.whisper_model_path),
            ("Qwen2.5-3B-Instruct Q4", "~2.0 GB  ·  text cleanup",
             self._cfg.llm_model_path),
        ]

        for i, (name, size_str, path) in enumerate(models):
            row_y = _H - 210 - i * 90
            self._add(_label(name, _PADDING, row_y + 36, _W - _PADDING * 2, 20,
                             size=13, bold=True, align=NSLeftTextAlignment))
            self._add(_label(size_str, _PADDING, row_y + 18, 300, 16,
                             size=11, align=NSLeftTextAlignment,
                             color=NSColor.secondaryLabelColor()))

            bar = NSProgressIndicator.alloc().initWithFrame_(
                NSMakeRect(_PADDING, row_y, _W - _PADDING * 2 - 90, 10)
            )
            bar.setStyle_(1)
            bar.setIndeterminate_(False)
            bar.setMinValue_(0)
            bar.setMaxValue_(100)
            bar.setDoubleValue_(100.0 if path.exists() else 0.0)
            self._add(bar)
            self._progress_bars.append(bar)

            status_text = "✓ Ready" if path.exists() else "Waiting…"
            sl = _label(status_text, _W - _PADDING - 80, row_y, 80, 16,
                        size=11, color=NSColor.secondaryLabelColor(),
                        align=NSLeftTextAlignment)
            self._add(sl)
            self._status_labels.append(sl)

        self._download_btn = self._btn(
            "Download Models", _PADDING, 24, 170, 32, self._start_download
        )
        self._download_btn.setEnabled_(not self._models_ready())
        self._add(self._download_btn)

        self._add(self._btn("← Back", _W // 2 - 50, 24, 100, 32, self._back))

        self._next_btn = self._btn(
            "Continue →", _W - 180 - _PADDING, 24, 180, 32, self._next
        )
        self._next_btn.setEnabled_(self._models_ready())
        self._add(self._next_btn)

    def _models_ready(self) -> bool:
        return (
            self._cfg.whisper_model_path.exists()
            and self._cfg.llm_model_path.exists()
        )

    def _start_download(self) -> None:
        if self._download_btn:
            self._download_btn.setEnabled_(False)
        threading.Thread(target=self._download_models, daemon=True).start()

    def _download_models(self) -> None:
        from huggingface_hub import snapshot_download, hf_hub_download
        from PyObjCTools import AppHelper

        tasks = [
            ("Systran/faster-distil-whisper-large-v3",
             self._cfg.whisper_model_path, None, 0),
            ("Qwen/Qwen2.5-3B-Instruct-GGUF",
             self._cfg.llm_model_path.parent,
             "qwen2.5-3b-instruct-q4_k_m.gguf", 1),
        ]

        for repo, dest, filename, idx in tasks:
            target = dest if filename is None else dest / filename
            if target.exists():
                self._set_progress(idx, 100, "✓ Ready")
                continue
            self._set_progress(idx, 2, "Downloading…")
            try:
                if filename is None:
                    snapshot_download(repo_id=repo, local_dir=str(dest),
                                      local_dir_use_symlinks=False)
                else:
                    hf_hub_download(repo_id=repo, filename=filename,
                                    local_dir=str(dest))
                self._set_progress(idx, 100, "✓ Done")
            except Exception as exc:
                self._set_progress(idx, 0, "Error")
                logger.error("Download failed: %s", exc)
                return

        def _enable() -> None:
            if self._next_btn:
                self._next_btn.setEnabled_(True)
        AppHelper.callAfter(_enable)

    def _set_progress(self, idx: int, value: float, status: str) -> None:
        from PyObjCTools import AppHelper
        def _do() -> None:
            if idx < len(self._progress_bars):
                self._progress_bars[idx].setDoubleValue_(value)
            if idx < len(self._status_labels):
                self._status_labels[idx].setStringValue_(status)
        AppHelper.callAfter(_do)

    # ------------------------------------------------------------------ #
    # Step: Hotkey                                                         #
    # ------------------------------------------------------------------ #

    def _step_hotkey(self) -> None:
        cx = _W / 2
        self._add(_label("You're all set!", cx - 160, _H - 90, 320, 40,
                         size=26, bold=True))
        self._add(_label("Here's how to use Open Flow:",
                         _PADDING, _H - 148, _W - _PADDING * 2, 26, size=15))

        steps = [
            ("1", "Click into any text field in any app."),
            ("2", f"Hold  {self._cfg.hotkey.replace('_', ' ').title()}  and speak."),
            ("3", "Release — your words appear instantly."),
        ]
        for i, (num, text) in enumerate(steps):
            row_y = _H - 220 - i * 60
            self._add(_label(num, _PADDING, row_y, 28, 28,
                             size=16, bold=True,
                             color=NSColor.systemBlueColor()))
            self._add(_label(text, _PADDING + 36, row_y,
                             _W - _PADDING * 2 - 36, 28,
                             size=14, align=NSLeftTextAlignment))

        self._add(_label(
            "Change the hotkey anytime from the  ◉  menu-bar icon → Preferences.",
            _PADDING, _H - 370, _W - _PADDING * 2, 20, size=12,
            color=NSColor.secondaryLabelColor(),
        ))

        self._add(self._btn("← Back", _PADDING, 24, 100, 32, self._back))
        self._add(self._btn("Start Dictating →", _W - 200 - _PADDING, 24, 200, 32,
                            self._finish))

    # ------------------------------------------------------------------ #
    # Finish                                                               #
    # ------------------------------------------------------------------ #

    def _finish(self) -> None:
        self._window.orderOut_(None)
        self._on_complete()
