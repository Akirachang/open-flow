"""First-run onboarding wizard — single-page WKWebView UI.

All four steps (welcome → microphone → hotkey → done) live in
`resources/welcome.html`. The Python side owns:
  - window lifecycle
  - microphone permission polling
  - background model download
  - JS ↔ Python bridge (WKUserContentController + evaluateJavaScript:)
"""

from __future__ import annotations

import json
import logging
import subprocess
import threading
from pathlib import Path
from typing import Callable

import objc
from AppKit import (
    NSApplication,
    NSBackingStoreBuffered,
    NSMakeRect,
    NSScreen,
    NSWindow,
    NSWindowStyleMaskClosable,
    NSWindowStyleMaskTitled,
)
from Foundation import NSURL, NSObject
from PyObjCTools import AppHelper
from WebKit import WKUserContentController, WKWebView, WKWebViewConfiguration

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------ #
# Constants
# ------------------------------------------------------------------ #

_W = 720
_H = 520

_WELCOME_HTML = Path(__file__).resolve().parent.parent / "resources" / "welcome.html"

# System Settings pane slugs
_PRIVACY_PANES = {
    "mic": "Privacy_Microphone",
    "accessibility": "Privacy_Accessibility",
    "input_monitoring": "Privacy_ListenEvent",
}


def _open_privacy_pane(key: str) -> None:
    pane = _PRIVACY_PANES.get(key)
    if not pane:
        logger.warning("Unknown privacy pane: %s", key)
        return
    url = f"x-apple.systempreferences:com.apple.preference.security?{pane}"
    logger.info("Opening privacy pane: %s", pane)
    try:
        subprocess.Popen(["open", url],
                         stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
    except Exception as exc:
        logger.error("Failed to open privacy pane %s: %s", pane, exc)


def _check_mic_permission() -> bool:
    """Return True if the process has microphone access.

    Uses AVCaptureDevice authorizationStatus — returns 3 when granted.
    """
    try:
        from AVFoundation import AVCaptureDevice, AVMediaTypeAudio
        status = AVCaptureDevice.authorizationStatusForMediaType_(AVMediaTypeAudio)
        return int(status) == 3  # AVAuthorizationStatusAuthorized
    except Exception as exc:
        logger.debug("Mic permission check unavailable: %s", exc)
        return False


# ------------------------------------------------------------------ #
# JS bridge delegate
# ------------------------------------------------------------------ #

class _WebMessageHandler(NSObject):
    """Routes `window.webkit.messageHandlers.openflow.postMessage(...)` calls."""

    def initWithCallback_(self, cb: Callable[[str, object], None]) -> "_WebMessageHandler":
        self = objc.super(_WebMessageHandler, self).init()
        self._cb = cb
        return self

    def userContentController_didReceiveScriptMessage_(self, _controller, message) -> None:
        try:
            body = message.body()
        except Exception:
            return
        # body is typically a dict {name, payload} but tolerate a bare string.
        if isinstance(body, str):
            name, payload = body, None
        else:
            try:
                name = str(body["name"])
                payload = body.get("payload") if hasattr(body, "get") else None
            except Exception:
                logger.warning("Unparseable web message: %r", body)
                return
        try:
            self._cb(name, payload)
        except Exception:
            logger.exception("Error handling web message %s", name)


# ------------------------------------------------------------------ #
# Wizard
# ------------------------------------------------------------------ #

class OnboardingWizard:
    def __init__(self, cfg, on_complete: Callable[[], None]) -> None:
        self._cfg = cfg
        self._on_complete = on_complete
        self._window: NSWindow | None = None
        self._web: WKWebView | None = None
        self._handler: _WebMessageHandler | None = None
        self._poll_stop = threading.Event()
        self._download_thread: threading.Thread | None = None
        self._ready = False

    # ------------------------------------------------------------------ #
    # Public                                                               #
    # ------------------------------------------------------------------ #

    def run(self) -> None:
        self._build_window()
        self._window.makeKeyAndOrderFront_(None)
        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
        self._start_permission_poll()
        self._start_background_download()

    # ------------------------------------------------------------------ #
    # Window + web view                                                    #
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
        self._window.setTitle_("Open Flow")
        self._window.setReleasedWhenClosed_(False)

        self._handler = _WebMessageHandler.alloc().initWithCallback_(self._on_web_message)
        controller = WKUserContentController.alloc().init()
        controller.addScriptMessageHandler_name_(self._handler, "openflow")

        config = WKWebViewConfiguration.alloc().init()
        config.setUserContentController_(controller)

        content = self._window.contentView()
        self._web = WKWebView.alloc().initWithFrame_configuration_(
            content.bounds(), config
        )
        self._web.setAutoresizingMask_(2 | 16)  # width + height resizable

        try:
            html = _WELCOME_HTML.read_text(encoding="utf-8")
            base_url = NSURL.fileURLWithPath_(str(_WELCOME_HTML.parent))
            self._web.loadHTMLString_baseURL_(html, base_url)
        except OSError as exc:
            logger.error("Failed to load wizard HTML: %s", exc)
            self._finish()
            return

        content.addSubview_(self._web)

    # ------------------------------------------------------------------ #
    # JS bridge — inbound                                                  #
    # ------------------------------------------------------------------ #

    def _on_web_message(self, name: str, payload: object) -> None:
        logger.debug("web msg: %s %r", name, payload)
        if name == "ready":
            self._ready = True
            self._push_state({"micGranted": _check_mic_permission()})
        elif name == "open_settings":
            _open_privacy_pane(str(payload) if payload else "mic")
        elif name == "step":
            # Purely informational — JS owns the current step.
            pass
        elif name == "skip" or name == "finish":
            self._finish()
        else:
            logger.debug("Unhandled web message: %s", name)

    # ------------------------------------------------------------------ #
    # JS bridge — outbound                                                 #
    # ------------------------------------------------------------------ #

    def _push_state(self, patch: dict) -> None:
        """Call `window.openflow.setState(patch)` in the web view."""
        if self._web is None:
            return
        js = f"window.openflow && window.openflow.setState({json.dumps(patch)});"
        def _run() -> None:
            self._web.evaluateJavaScript_completionHandler_(js, None)
        AppHelper.callAfter(_run)

    # ------------------------------------------------------------------ #
    # Permission polling                                                   #
    # ------------------------------------------------------------------ #

    def _start_permission_poll(self) -> None:
        """Poll mic permission every 500ms and push updates to JS."""
        last = {"mic": None}

        def tick() -> None:
            if self._poll_stop.is_set():
                return
            granted = _check_mic_permission()
            if granted != last["mic"]:
                last["mic"] = granted
                if self._ready:
                    self._push_state({"micGranted": bool(granted)})

        def loop() -> None:
            while not self._poll_stop.is_set():
                AppHelper.callAfter(tick)
                self._poll_stop.wait(0.5)

        threading.Thread(target=loop, daemon=True, name="of-perm-poll").start()

    # ------------------------------------------------------------------ #
    # Background model download                                            #
    # ------------------------------------------------------------------ #

    def _start_background_download(self) -> None:
        """Kick off model downloads if missing — runs silently while wizard is up.

        If they're not ready by the time the user hits Start, the tray app
        surfaces a notification separately.
        """
        if self._models_ready():
            return

        def worker() -> None:
            try:
                from huggingface_hub import hf_hub_download, snapshot_download
            except Exception as exc:
                logger.error("huggingface_hub unavailable: %s", exc)
                return

            tasks = [
                ("Systran/faster-distil-whisper-large-v3",
                 self._cfg.whisper_model_path, None),
                ("Qwen/Qwen2.5-3B-Instruct-GGUF",
                 self._cfg.llm_model_path.parent,
                 "qwen2.5-3b-instruct-q4_k_m.gguf"),
            ]
            for repo, dest, filename in tasks:
                target = dest if filename is None else dest / filename
                if target.exists():
                    continue
                try:
                    if filename is None:
                        snapshot_download(repo_id=repo, local_dir=str(dest),
                                          local_dir_use_symlinks=False)
                    else:
                        hf_hub_download(repo_id=repo, filename=filename,
                                        local_dir=str(dest))
                except Exception as exc:
                    logger.error("Model download failed (%s): %s", repo, exc)
                    return

        self._download_thread = threading.Thread(
            target=worker, daemon=True, name="of-model-download"
        )
        self._download_thread.start()

    def _models_ready(self) -> bool:
        return (
            self._cfg.whisper_model_path.exists()
            and self._cfg.llm_model_path.exists()
        )

    # ------------------------------------------------------------------ #
    # Finish                                                               #
    # ------------------------------------------------------------------ #

    def _finish(self) -> None:
        self._poll_stop.set()
        if self._window is not None:
            self._window.orderOut_(None)
        self._on_complete()
