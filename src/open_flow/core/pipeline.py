"""Dictation pipeline — transcribe, clean, inject.

Pure orchestration logic. No UI framework imports here — the caller provides
status callbacks for progress updates and receives a structured result.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable, Optional

import numpy as np

from open_flow.core.cleanup import Cleaner
from open_flow.core.inject import inject as inject_text
from open_flow.core.transcribe import Transcriber

logger = logging.getLogger(__name__)


@dataclass
class PipelineResult:
    text: Optional[str]         # final text that was (or would have been) injected
    injected: bool              # True if successfully pasted into the focused app
    raw_text: Optional[str] = None       # pre-cleanup transcript
    skipped_reason: Optional[str] = None  # "no_speech" | "password_field" | "error"
    error: Optional[str] = None


class DictationPipeline:
    """
    Runs the transcribe → clean → inject flow on a pre-captured audio buffer.

    `on_status` is called with short human-readable state strings
    ("Transcribing…", "Cleaning…") so the UI can reflect progress.
    """

    def __init__(
        self,
        transcriber: Transcriber,
        cleaner: Optional[Cleaner] = None,
    ) -> None:
        self._transcriber = transcriber
        self._cleaner = cleaner

    def set_cleaner(self, cleaner: Optional[Cleaner]) -> None:
        self._cleaner = cleaner

    def run(
        self,
        audio: np.ndarray,
        record_duration: float,
        on_status: Callable[[str], None] = lambda s: None,
    ) -> PipelineResult:
        try:
            on_status("Transcribing…")
            raw = self._transcriber.transcribe(audio, record_duration)

            if not raw:
                return PipelineResult(text=None, raw_text=None, injected=False,
                                      skipped_reason="no_speech")

            text = raw
            if self._cleaner is not None:
                on_status("Cleaning…")
                text = self._cleaner.clean(raw, record_duration)

            on_status("Injecting…")
            injected = inject_text(text)
            if not injected:
                return PipelineResult(text=text, raw_text=raw, injected=False,
                                      skipped_reason="password_field")

            return PipelineResult(text=text, raw_text=raw, injected=True)

        except Exception as exc:
            logger.exception("Pipeline error")
            return PipelineResult(text=None, raw_text=None, injected=False,
                                  skipped_reason="error", error=str(exc))
