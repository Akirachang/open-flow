"""Microphone capture into an in-memory buffer."""

from __future__ import annotations

import logging
import wave
from pathlib import Path
from threading import Event, Lock
from typing import Any, Callable, Optional

import numpy as np
import sounddevice as sd

logger = logging.getLogger(__name__)

DTYPE = np.int16
LAST_WAV = Path("/tmp/open_flow_last.wav")


class AudioRecorder:
    def __init__(self, sample_rate: int = 16000, channels: int = 1) -> None:
        self.sample_rate = sample_rate
        self.channels = channels
        self._chunks: list[np.ndarray] = []
        self._lock = Lock()
        self._stream: sd.InputStream | None = None
        self._recording = Event()
        self.on_chunk: Optional[Callable[[np.ndarray], None]] = None

    def _callback(self, indata: np.ndarray, frames: int, time: Any, status: sd.CallbackFlags) -> None:  # noqa: ANN401
        if status:
            logger.warning("sounddevice status: %s", status)
        if self._recording.is_set():
            chunk = indata.copy()
            with self._lock:
                self._chunks.append(chunk)
            if self.on_chunk is not None:
                self.on_chunk(chunk.flatten())

    def start(self) -> None:
        if self._stream is not None:
            return
        self._chunks.clear()
        self._recording.set()
        self._stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=self.channels,
            dtype=DTYPE,
            callback=self._callback,
            blocksize=1024,
        )
        self._stream.start()
        logger.info("Recording started")

    def stop(self) -> np.ndarray:
        self._recording.clear()
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        with self._lock:
            if self._chunks:
                audio = np.concatenate(self._chunks, axis=0).flatten()
            else:
                audio = np.array([], dtype=DTYPE)
        duration = len(audio) / self.sample_rate
        logger.info("Recording stopped — %.2fs captured", duration)
        return audio

    def save_wav(self, audio: np.ndarray, path: Path = LAST_WAV) -> None:
        with wave.open(str(path), "w") as wf:
            wf.setnchannels(self.channels)
            wf.setsampwidth(2)  # int16 = 2 bytes
            wf.setframerate(self.sample_rate)
            wf.writeframes(audio.tobytes())
        logger.info("Saved WAV → %s", path)
