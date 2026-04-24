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

# System Settings pane slugs — keyed by the short names the JS sends.
_PRIVACY_PANES = {
    "mic": "Privacy_Microphone",
    "ax": "Privacy_Accessibility",
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


_AV_STATUS_NOT_DETERMINED = 0
_AV_STATUS_AUTHORIZED = 3


def _mic_auth_status() -> int:
    try:
        from AVFoundation import AVCaptureDevice, AVMediaTypeAudio
        return int(AVCaptureDevice.authorizationStatusForMediaType_(AVMediaTypeAudio))
    except Exception as exc:
        logger.debug("Mic permission check unavailable: %s", exc)
        return -1


def _check_mic_permission() -> bool:
    return _mic_auth_status() == _AV_STATUS_AUTHORIZED


def _request_mic_permission(on_result: Callable[[bool], None]) -> None:
    """Trigger the native mic permission prompt.

    If status is already determined (granted or denied), this returns the
    current answer asynchronously without showing a dialog. A denied-then-
    reset grant requires the user to toggle the Privacy pane — we open it
    for them in the denied branch.
    """
    try:
        from AVFoundation import AVCaptureDevice, AVMediaTypeAudio
    except Exception as exc:
        logger.debug("AVFoundation unavailable: %s", exc)
        on_result(False)
        return

    status = _mic_auth_status()
    if status == _AV_STATUS_AUTHORIZED:
        on_result(True)
        return
    if status not in (_AV_STATUS_NOT_DETERMINED, -1):
        # Denied or restricted — the prompt won't appear again.
        # Open the Privacy pane so the user can flip the toggle.
        _open_privacy_pane("mic")
        on_result(False)
        return

    def completion(granted: bool) -> None:
        on_result(bool(granted))

    AVCaptureDevice.requestAccessForMediaType_completionHandler_(
        AVMediaTypeAudio, completion
    )


def _check_accessibility() -> bool:
    try:
        from ApplicationServices import AXIsProcessTrusted
        return bool(AXIsProcessTrusted())
    except Exception as exc:
        logger.debug("AX permission check unavailable: %s", exc)
        return False


def _request_accessibility() -> bool:
    """Trigger the native Accessibility sheet via AXIsProcessTrustedWithOptions.

    The sheet appears only when status is 'not determined'. If the user
    previously denied, we fall back to opening the Privacy pane so they can
    toggle the switch manually. Returns the *current* trusted value (not the
    post-prompt one — the sheet is async).
    """
    try:
        from ApplicationServices import (
            AXIsProcessTrusted,
            AXIsProcessTrustedWithOptions,
            kAXTrustedCheckOptionPrompt,
        )
    except Exception as exc:
        logger.debug("AX APIs unavailable: %s", exc)
        _open_privacy_pane("ax")
        return False

    if AXIsProcessTrusted():
        return True

    # Show the system sheet. If a prior denial means the sheet won't appear,
    # also nudge the user toward the Privacy pane.
    try:
        options = {kAXTrustedCheckOptionPrompt: True}
        trusted = bool(AXIsProcessTrustedWithOptions(options))
    except Exception as exc:
        logger.debug("AXIsProcessTrustedWithOptions failed: %s", exc)
        trusted = False

    if not trusted:
        _open_privacy_pane("ax")
    return trusted


# ------------------------------------------------------------------ #
# JS bridge delegate
# ------------------------------------------------------------------ #

class _WindowCloseDelegate(NSObject):
    """Treats closing the wizard window as finishing onboarding."""

    def initWithCallback_(self, cb: Callable[[], None]) -> "_WindowCloseDelegate":
        self = objc.super(_WindowCloseDelegate, self).init()
        self._cb = cb
        return self

    def windowWillClose_(self, _notification) -> None:
        try:
            self._cb()
        except Exception:
            logger.exception("Error in window close callback")


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
        self._finished = False
        self._close_delegate: _WindowCloseDelegate | None = None

    # ------------------------------------------------------------------ #
    # Public                                                               #
    # ------------------------------------------------------------------ #

    def run(self) -> None:
        self._build_window()
        self._window.makeKeyAndOrderFront_(None)
        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
        # The web view must be first responder or JS keydown/keyup never fires.
        if self._web is not None:
            self._window.makeFirstResponder_(self._web)
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

        # Closing the window (red traffic light) should count as finishing —
        # otherwise the user re-enters the wizard on every launch.
        self._close_delegate = _WindowCloseDelegate.alloc().initWithCallback_(
            self._finish
        )
        self._window.setDelegate_(self._close_delegate)

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
            self._push_state({
                "micGranted": _check_mic_permission(),
                "axGranted": _check_accessibility(),
            })
        elif name == "open_settings":
            key = str(payload) if payload else "mic"
            if key == "mic":
                def _after(granted: bool) -> None:
                    if self._ready:
                        self._push_state({"micGranted": bool(granted)})
                _request_mic_permission(_after)
            elif key == "ax":
                trusted = _request_accessibility()
                if self._ready:
                    self._push_state({"axGranted": bool(trusted)})
            else:
                _open_privacy_pane(key)
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
        """Poll mic + AX every 500ms and push diffs to JS."""
        last = {"mic": None, "ax": None}

        def tick() -> None:
            if self._poll_stop.is_set():
                return
            patch: dict = {}
            mic = _check_mic_permission()
            if mic != last["mic"]:
                last["mic"] = mic
                patch["micGranted"] = bool(mic)
            ax = _check_accessibility()
            if ax != last["ax"]:
                last["ax"] = ax
                patch["axGranted"] = bool(ax)
            if patch and self._ready:
                self._push_state(patch)

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
        if self._finished:
            return
        self._finished = True
        self._poll_stop.set()
        if self._window is not None:
            # Detach the delegate first so orderOut_ doesn't re-enter _finish.
            self._window.setDelegate_(None)
            self._window.orderOut_(None)
        self._on_complete()
