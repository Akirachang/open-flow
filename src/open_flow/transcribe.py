"""Whisper transcription via faster-whisper."""

from __future__ import annotations

import logging
import time
from pathlib import Path

import numpy as np
from faster_whisper import WhisperModel

from open_flow.config import Config

logger = logging.getLogger(__name__)

# Whisper hallucination blocklist — common silent-audio outputs
_HALLUCINATIONS: frozenset[str] = frozenset(
    [
        "thanks for watching",
        "thank you for watching",
        "please subscribe",
        "subscribe to my channel",
        "like and subscribe",
        "you",
        "",
    ]
)


class Transcriber:
    def __init__(self, cfg: Config) -> None:
        self._cfg = cfg
        self._model: WhisperModel | None = None

    def load(self) -> None:
        model_path = self._cfg.whisper_model_path
        if not model_path.exists():
            raise FileNotFoundError(
                f"Whisper model not found at {model_path}. "
                "Run: uv run python scripts/download_models.py"
            )
        logger.info("Loading Whisper model from %s …", model_path)
        t0 = time.monotonic()
        self._model = WhisperModel(
            str(model_path),
            device="cpu",
            compute_type=self._cfg.whisper_compute_type,
        )
        logger.info("Whisper loaded in %.2fs", time.monotonic() - t0)

    def transcribe(self, audio: np.ndarray, record_duration: float) -> str | None:
        if self._model is None:
            raise RuntimeError("Transcriber not loaded — call load() first")

        if record_duration < self._cfg.min_audio_seconds:
            logger.info("Audio too short (%.2fs), skipping transcription", record_duration)
            return None

        t0 = time.monotonic()
        segments, info = self._model.transcribe(
            audio.astype(np.float32) / 32768.0,
            language="en",
            condition_on_previous_text=False,
            no_speech_threshold=self._cfg.no_speech_threshold,
            vad_filter=True,
        )
        text = " ".join(seg.text.strip() for seg in segments).strip()
        transcribe_duration = time.monotonic() - t0

        logger.info(
            "Transcribed in %.2fs | record=%.2fs | total=%.2fs | text=%r",
            transcribe_duration,
            record_duration,
            record_duration + transcribe_duration,
            text,
        )

        if self._is_hallucination(text):
            logger.info("Hallucination detected, discarding: %r", text)
            return None

        return text or None

    def _is_hallucination(self, text: str) -> bool:
        normalized = text.lower().strip().rstrip(".")
        return normalized in _HALLUCINATIONS
