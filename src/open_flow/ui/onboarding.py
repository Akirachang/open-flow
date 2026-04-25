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
import time
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
        # Live demo on the hotkey-try-it step. Lazily created so we never
        # touch the audio device or load Whisper until the user actually
        # holds the key.
        self._demo_recorder = None
        self._demo_transcriber = None
        self._demo_start_time: float = 0.0

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
            # If the models are already on disk we can skip the Download
            # button and warm them straight away.
            if self._models_ready():
                self._start_background_download()
        elif name == "start_download":
            self._start_background_download()
        elif name == "start_record":
            self._demo_start()
        elif name == "stop_record":
            self._demo_stop()
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
    # Background setup: download models + warm Whisper                     #
    # ------------------------------------------------------------------ #

    # Approximate sizes for progress estimation (disk-poll-based).
    _WHISPER_SIZE_BYTES = 1_500_000_000   # ~1.5 GB
    _LLM_SIZE_BYTES = 2_000_000_000       # ~2.0 GB

    def _push_setup(self, patch: dict) -> None:
        """Call window.openflow.setSetup(patch) on the main thread."""
        if self._web is None:
            return
        js = f"window.openflow && window.openflow.setSetup({json.dumps(patch)});"
        AppHelper.callAfter(
            lambda: self._web.evaluateJavaScript_completionHandler_(js, None)
        )

    def _start_background_download(self) -> None:
        """Download Whisper + Qwen, then warm Whisper. Pushes progress to JS.

        Idempotent — if the worker is already running, calling again is a no-op.
        """
        if self._download_thread is not None and self._download_thread.is_alive():
            return
        self._download_thread = threading.Thread(
            target=self._setup_worker, daemon=True, name="of-setup"
        )
        self._download_thread.start()

    def _setup_worker(self) -> None:
        """Drive a single combined progress bar across:
            whisper download   →  0..weight_w%
            qwen download      →  weight_w..(weight_w+weight_l)%   (≈100)
            warm-up            →  indeterminate "warming" pulse, then 100%
        """
        total = self._WHISPER_SIZE_BYTES + self._LLM_SIZE_BYTES
        weight_w = self._WHISPER_SIZE_BYTES / total * 100  # ≈ 42.86
        weight_l = self._LLM_SIZE_BYTES / total * 100      # ≈ 57.14

        whisper_path = self._cfg.whisper_model_path
        llm_path = self._cfg.llm_model_path

        whisper_done = whisper_path.exists()
        llm_done = llm_path.exists()
        base_pct = (weight_w if whisper_done else 0.0) + (weight_l if llm_done else 0.0)

        # Tell the UI where we're starting so the bar isn't stuck at 0%.
        if base_pct > 0:
            self._push_setup({
                "state": "downloading",
                "status": "Resuming setup",
                "pct": int(round(base_pct)),
            })

        # Whisper ----------------------------------------------------------
        if not whisper_done:
            ok = self._download_with_progress(
                target_dir=whisper_path,
                repo="Systran/faster-distil-whisper-large-v3",
                filename=None,
                expected_bytes=self._WHISPER_SIZE_BYTES,
                base_pct=0.0,
                weight=weight_w,
                status="Downloading speech model",
            )
            if not ok:
                self._push_setup({
                    "state": "error",
                    "status": "Download failed — check your connection",
                })
                return
            base_pct = weight_w

        # LLM (optional) ---------------------------------------------------
        if not llm_done:
            ok = self._download_with_progress(
                target_dir=llm_path.parent,
                repo="Qwen/Qwen2.5-3B-Instruct-GGUF",
                filename=llm_path.name,
                expected_bytes=self._LLM_SIZE_BYTES,
                base_pct=base_pct,
                weight=weight_l,
                status="Downloading cleanup model",
            )
            if not ok:
                # LLM is optional — log it, push to base_pct + weight_l so the bar
                # still completes and the user can continue (cleanup off).
                logger.warning("LLM download failed; continuing without it")
            base_pct = base_pct + weight_l

        # Warm Whisper into memory ----------------------------------------
        self._push_setup({
            "state": "warming",
            "status": "Warming up the speech model",
            "pct": 100,
        })
        try:
            from open_flow.core.transcribe import Transcriber
            transcriber = Transcriber(self._cfg)
            transcriber.load()
            # Stash so the hotkey-try-it step can reuse the warmed instance.
            self._demo_transcriber = transcriber
        except Exception as exc:
            logger.exception("Whisper warm-up failed")
            self._push_setup({
                "state": "error",
                "status": f"Warm-up failed: {str(exc)[:60]}",
            })
            return

        self._push_setup({
            "state": "ready",
            "status": "Ready to dictate.",
            "pct": 100,
        })

    def _download_with_progress(
        self,
        *,
        target_dir: Path,
        repo: str,
        filename: str | None,
        expected_bytes: int,
        base_pct: float,
        weight: float,
        status: str,
    ) -> bool:
        """Run an HF download in a sub-thread; poll disk and push combined pct."""
        try:
            from huggingface_hub import hf_hub_download, snapshot_download
        except Exception as exc:
            logger.error("huggingface_hub unavailable: %s", exc)
            return False

        result: dict = {"err": None}

        def runner() -> None:
            try:
                if filename is None:
                    snapshot_download(
                        repo_id=repo,
                        local_dir=str(target_dir),
                        local_dir_use_symlinks=False,
                    )
                else:
                    hf_hub_download(
                        repo_id=repo, filename=filename, local_dir=str(target_dir)
                    )
            except Exception as exc:
                result["err"] = exc

        t = threading.Thread(target=runner, daemon=True, name=f"of-dl-{repo}")
        t.start()

        while t.is_alive():
            local = self._estimate_pct(target_dir, expected_bytes)
            combined = base_pct + (local / 100.0) * weight
            self._push_setup({
                "state": "downloading",
                "status": status,
                "pct": int(round(min(99.0, combined))),
            })
            t.join(timeout=0.5)

        if result["err"] is not None:
            logger.error("Model download failed (%s): %s", repo, result["err"])
            return False

        self._push_setup({
            "state": "downloading",
            "status": status,
            "pct": int(round(base_pct + weight)),
        })
        return True

    @staticmethod
    def _estimate_pct(path: Path, expected_bytes: int) -> int:
        """Estimate download % by walking directory size on disk."""
        try:
            if path.is_file():
                size = path.stat().st_size
            elif path.exists():
                size = sum(
                    p.stat().st_size for p in path.rglob("*") if p.is_file()
                )
            else:
                size = 0
        except OSError:
            size = 0
        if expected_bytes <= 0:
            return 0
        return max(0, min(99, int(size * 100 / expected_bytes)))

    def _models_ready(self) -> bool:
        return (
            self._cfg.whisper_model_path.exists()
            and self._cfg.llm_model_path.exists()
        )

    # ------------------------------------------------------------------ #
    # Live demo (hotkey try-it step)                                       #
    # ------------------------------------------------------------------ #

    def _push_transcript(self, text: str) -> None:
        """Call window.openflow.setTranscript({text}) on the main thread."""
        if self._web is None:
            return
        js = f"window.openflow && window.openflow.setTranscript({json.dumps({'text': text})});"
        AppHelper.callAfter(
            lambda: self._web.evaluateJavaScript_completionHandler_(js, None)
        )

    def _demo_start(self) -> None:
        """Begin recording when the user holds Right Option on step 3."""
        try:
            if self._demo_recorder is None:
                from open_flow.core.audio import AudioRecorder
                self._demo_recorder = AudioRecorder(
                    sample_rate=self._cfg.sample_rate,
                    channels=self._cfg.channels,
                )
            self._demo_start_time = time.monotonic()
            self._demo_recorder.start()
        except Exception:
            logger.exception("Demo: recorder start failed")
            self._push_transcript("")

    def _demo_stop(self) -> None:
        """Stop recording, transcribe, and push the result back to JS."""
        if self._demo_recorder is None:
            self._push_transcript("")
            return
        try:
            audio = self._demo_recorder.stop()
        except Exception:
            logger.exception("Demo: recorder stop failed")
            self._push_transcript("")
            return

        duration = max(0.0, time.monotonic() - self._demo_start_time)

        threading.Thread(
            target=self._demo_transcribe_worker,
            args=(audio, duration),
            daemon=True,
            name="of-demo-transcribe",
        ).start()

    def _demo_transcribe_worker(self, audio, duration: float) -> None:
        try:
            transcriber = self._demo_transcriber
            if transcriber is None:
                # Models may have been on disk already and we never warmed.
                from open_flow.core.transcribe import Transcriber
                transcriber = Transcriber(self._cfg)
                transcriber.load()
                self._demo_transcriber = transcriber

            text = transcriber.transcribe(audio, duration) or ""
        except Exception:
            logger.exception("Demo: transcription failed")
            text = ""

        self._push_transcript(text.strip())

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
