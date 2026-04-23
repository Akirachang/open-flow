"""Download Whisper and LLM model files into ~/.cache/open_flow/models/."""

from __future__ import annotations

import sys
from pathlib import Path

# Add src to path so we can import open_flow without installing
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from open_flow.config import MODELS_DIR, load

WHISPER_REPO = "Systran/faster-distil-whisper-large-v3"
LLM_REPO = "Qwen/Qwen2.5-3B-Instruct-GGUF"
LLM_FILE = "qwen2.5-3b-instruct-q4_k_m.gguf"


def download_whisper(models_dir: Path) -> None:
    from huggingface_hub import snapshot_download

    dest = models_dir / "faster-distil-whisper-large-v3"
    if dest.exists():
        print(f"Whisper model already at {dest}, skipping.")
        return
    print(f"Downloading Whisper distil-large-v3 → {dest} …")
    snapshot_download(repo_id=WHISPER_REPO, local_dir=str(dest))
    print("Whisper model downloaded.")


def download_llm(models_dir: Path) -> None:
    from huggingface_hub import hf_hub_download

    dest = models_dir / LLM_FILE
    if dest.exists():
        print(f"LLM model already at {dest}, skipping.")
        return
    print(f"Downloading {LLM_FILE} → {dest} …")
    models_dir.mkdir(parents=True, exist_ok=True)
    hf_hub_download(repo_id=LLM_REPO, filename=LLM_FILE, local_dir=str(models_dir))
    print("LLM model downloaded.")


def main() -> None:
    cfg = load()
    models_dir = cfg.models_path
    models_dir.mkdir(parents=True, exist_ok=True)
    print(f"Models directory: {models_dir}\n")
    download_whisper(models_dir)
    print()
    download_llm(models_dir)
    print("\nAll models ready.")


if __name__ == "__main__":
    main()
