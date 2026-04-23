"""Whisper transcription via faster-whisper."""

from __future__ import annotations

import logging
import time
from pathlib import Path

import numpy as np
from faster_whisper import WhisperModel

from open_flow.config import Config

logger = logging.getLogger(__name__)

# RMS energy threshold below which a frame is considered silence (0–1 scale)
_VAD_THRESHOLD = 0.01
# Frame size for VAD energy check (~20ms at 16kHz)
_VAD_FRAME = 320
# Pad this many frames of context either side of speech so we don't clip words
_VAD_PADDING_FRAMES = 8

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


def _vad_trim(audio: np.ndarray) -> np.ndarray:
    """Strip leading and trailing silence based on RMS energy per frame."""
    if len(audio) == 0:
        return audio

    float_audio = audio.astype(np.float32) / 32768.0
    n_frames = len(float_audio) // _VAD_FRAME
    if n_frames == 0:
        return audio

    # Compute RMS for each frame
    frames = float_audio[: n_frames * _VAD_FRAME].reshape(n_frames, _VAD_FRAME)
    rms = np.sqrt(np.mean(frames ** 2, axis=1))
    speech = rms > _VAD_THRESHOLD

    if not np.any(speech):
        return audio  # all silence — return as-is, let hallucination filter handle it

    first = max(0, np.argmax(speech) - _VAD_PADDING_FRAMES)
    last = min(n_frames, len(speech) - np.argmax(speech[::-1]) + _VAD_PADDING_FRAMES)

    return audio[first * _VAD_FRAME : last * _VAD_FRAME]


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

        audio = _vad_trim(audio)
        trimmed_duration = len(audio) / self._cfg.sample_rate

        if trimmed_duration < self._cfg.min_audio_seconds:
            logger.info("Audio is silence after VAD trim, skipping")
            return None

        logger.debug("VAD trim: %.2fs → %.2fs", record_duration, trimmed_duration)

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
