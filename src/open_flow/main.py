"""Entry point — Phase 4: hotkey + audio + transcription + LLM cleanup + injection."""

from __future__ import annotations

import logging
import signal
import sys
import time
from threading import Thread

from open_flow import config as cfg_module
from open_flow.audio import AudioRecorder, LAST_WAV
from open_flow.cleanup import Cleaner
from open_flow.hotkey import HotkeyListener
from open_flow.inject import inject
from open_flow.permissions import check_all, open_accessibility_settings
from open_flow.transcribe import Transcriber

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def main() -> None:
    cfg = cfg_module.load()

    if not check_all():
        print("\nAccessibility permission is required for text injection.")
        print("Opening System Settings…")
        open_accessibility_settings()
        print("Grant access, then relaunch open-flow.")
        sys.exit(1)

    recorder = AudioRecorder(sample_rate=cfg.sample_rate, channels=cfg.channels)
    transcriber = Transcriber(cfg)
    cleaner = Cleaner(cfg) if cfg.llm_enabled else None

    print("Loading Whisper model…")
    transcriber.load()

    if cleaner is not None:
        print("Loading LLM…")
        cleaner.load()

    print("Ready.\n")

    _start_time: float = 0.0

    def on_press() -> None:
        nonlocal _start_time
        _start_time = time.monotonic()
        recorder.start()
        print("● Recording…", flush=True)

    def on_release() -> None:
        audio = recorder.stop()
        record_duration = time.monotonic() - _start_time
        recorder.save_wav(audio, LAST_WAV)

        def _process() -> None:
            t0 = time.monotonic()

            print("  Transcribing…", flush=True)
            text = transcriber.transcribe(audio, record_duration)
            if not text:
                print("  → (no speech detected)\n", flush=True)
                return

            if cleaner is not None:
                print("  Cleaning…", flush=True)
                text = cleaner.clean(text, record_duration)

            print(f"  → {text}", flush=True)

            injected = inject(text)
            total = time.monotonic() - t0 + record_duration
            status = "injected" if injected else "skipped (password field)"
            print(f"  ✓ {status} | total latency {total:.2f}s\n", flush=True)

        Thread(target=_process, daemon=True).start()

    hotkey = HotkeyListener(
        key_name=cfg.hotkey,
        on_press=on_press,
        on_release=on_release,
    )
    hotkey.start()

    llm_status = "on" if cfg.llm_enabled else "off"
    print("Open Flow — Phase 4")
    print(f"Hold [{cfg.hotkey}] to record. LLM cleanup={llm_status}. Ctrl-C to quit.\n")

    def _shutdown(sig: int, frame: object) -> None:
        print("\nShutting down…")
        hotkey.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    signal.pause()
