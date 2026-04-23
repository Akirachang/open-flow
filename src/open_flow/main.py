"""Entry point — Phase 2: hotkey + audio capture + Whisper transcription."""

from __future__ import annotations

import logging
import signal
import sys
import time
from threading import Thread

from open_flow import config as cfg_module
from open_flow.audio import AudioRecorder, LAST_WAV
from open_flow.hotkey import HotkeyListener
from open_flow.transcribe import Transcriber

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def main() -> None:
    cfg = cfg_module.load()
    recorder = AudioRecorder(sample_rate=cfg.sample_rate, channels=cfg.channels)
    transcriber = Transcriber(cfg)

    print("Loading Whisper model… (first run may take a few seconds)")
    transcriber.load()
    print("Model ready.\n")

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

        def _transcribe() -> None:
            print("  Transcribing…", flush=True)
            text = transcriber.transcribe(audio, record_duration)
            if text:
                print(f"  → {text}\n", flush=True)
            else:
                print("  → (no speech detected)\n", flush=True)

        Thread(target=_transcribe, daemon=True).start()

    hotkey = HotkeyListener(
        key_name=cfg.hotkey,
        on_press=on_press,
        on_release=on_release,
    )
    hotkey.start()

    print(f"Open Flow — Phase 2")
    print(f"Hold [{cfg.hotkey}] to record. Press Ctrl-C to quit.\n")

    def _shutdown(sig: int, frame: object) -> None:
        print("\nShutting down…")
        hotkey.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    signal.pause()
