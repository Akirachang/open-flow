"""Config load/save backed by ~/.config/open_flow/config.toml."""

from __future__ import annotations

import tomllib
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import tomli_w

CONFIG_PATH = Path.home() / ".config" / "open_flow" / "config.toml"
MODELS_DIR = Path.home() / ".cache" / "open_flow" / "models"


@dataclass
class Config:
    hotkey: str = "right_alt"
    sample_rate: int = 16000
    channels: int = 1
    whisper_model: str = "faster-distil-whisper-large-v3"
    whisper_compute_type: str = "int8"
    llm_model: str = "qwen2.5-3b-instruct-q4_k_m.gguf"
    llm_enabled: bool = True
    llm_min_words: int = 10
    llm_min_seconds: float = 2.0
    no_speech_threshold: float = 0.6
    min_audio_seconds: float = 0.3
    models_dir: str = field(default_factory=lambda: str(MODELS_DIR))
    onboarding_complete: bool = False

    @property
    def models_path(self) -> Path:
        return Path(self.models_dir)

    @property
    def whisper_model_path(self) -> Path:
        return self.models_path / self.whisper_model

    @property
    def llm_model_path(self) -> Path:
        return self.models_path / self.llm_model


# Hugging Face renamed this file to all-lowercase upstream, so the old
# default 404s on download. Migrate any persisted config that still points
# at the old name to the new one — silent and surgical.
_LLM_RENAMES: dict[str, str] = {
    "Qwen2.5-3B-Instruct-Q4_K_M.gguf": "qwen2.5-3b-instruct-q4_k_m.gguf",
}


def load() -> Config:
    if not CONFIG_PATH.exists():
        cfg = Config()
        save(cfg)
        return cfg
    with CONFIG_PATH.open("rb") as f:
        data: dict[str, Any] = tomllib.load(f)
    cfg = Config(**{k: v for k, v in data.items() if k in Config.__dataclass_fields__})
    new_name = _LLM_RENAMES.get(cfg.llm_model)
    if new_name is not None:
        cfg.llm_model = new_name
        save(cfg)
    return cfg


def save(cfg: Config) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    # Atomic write: a concurrent reader (e.g. a second instance launched by
    # launchd right after we save) must never observe a truncated file.
    tmp = CONFIG_PATH.with_suffix(CONFIG_PATH.suffix + ".tmp")
    with tmp.open("wb") as f:
        tomli_w.dump(asdict(cfg), f)
        f.flush()
    tmp.replace(CONFIG_PATH)
