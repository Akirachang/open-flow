# Open Flow

Offline, open-source push-to-talk voice dictation for macOS.

Hold a hotkey, speak, release → transcribed text appears in whatever app has focus. Everything runs locally. No cloud. No subscription. No data leaves your machine.

---

## 📖 Overview

Open Flow is a macOS menu-bar app that lets you dictate text into any application using a push-to-talk hotkey. It uses a local Whisper model for transcription and an optional local LLM to clean up filler words and self-corrections before injecting the result.

---

## 🚀 Installation

### One-line install (recommended)

```bash
curl -fsSL https://raw.githubusercontent.com/Akirachang/open-flow/main/install.sh | bash
```

Downloads the latest signed DMG, drops `Open Flow.app` into `/Applications`, and launches it. The first-run wizard handles permissions and model downloads.

To uninstall:

```bash
curl -fsSL https://raw.githubusercontent.com/Akirachang/open-flow/main/uninstall.sh | bash
```

### Run from source (development)

Requirements: macOS on Apple Silicon (M1+), Python 3.11+, and [`uv`](https://github.com/astral-sh/uv).

```bash
# 1. Clone the repo
git clone https://github.com/Akirachang/open-flow.git
cd open-flow

# 2. Install dependencies (builds llama-cpp-python with Metal support)
CMAKE_ARGS="-DGGML_METAL=on" uv sync

# 3. Download models (~1.5GB Whisper + ~2GB LLM)
uv run python scripts/download_models.py

# 4. Run
uv run open-flow
```

### macOS Permissions

On first launch, macOS will prompt for permissions. All three are required:

| Permission | Why |
|---|---|
| **Microphone** | To record your voice |
| **Input Monitoring** | For the global hotkey to work |
| **Accessibility** | For text injection via Cmd+V synthesis |

Grant them in **System Settings → Privacy & Security**, then relaunch the app.

---

## 💻 Usage

1. Launch `uv run open-flow` — a `◉` icon appears in the menu bar
2. Wait for `Idle — hold right_alt to dictate` in the status
3. Click into any text field in any app
4. **Hold Right Option** → speak → **release**
5. The transcribed (and optionally cleaned) text is injected at the cursor

### Menu Bar States

| Icon | Meaning |
|---|---|
| `◉` | Idle, ready to record |
| `🔴` | Recording |
| `⏳` | Transcribing / cleaning |
| `⚠️` | Error |

### Menu Items

- **Status** — live state and last transcript preview with latency
- **LLM Cleanup: on/off** — toggle LLM cleanup, persisted to config
- **Preferences…** — change the hotkey (takes effect immediately)
- **Quit** — clean shutdown

---

## ⚙️ Configuration

Config is stored at `~/.config/open_flow/config.toml` and is created automatically on first run.

```toml
hotkey = "right_alt"          # right_alt, right_ctrl, right_shift, f13, f14, f15
sample_rate = 16000
channels = 1
whisper_model = "faster-distil-whisper-large-v3"
whisper_compute_type = "int8"
llm_model = "Qwen2.5-3B-Instruct-Q4_K_M.gguf"
llm_enabled = true
llm_min_words = 10            # skip LLM for utterances shorter than this
llm_min_seconds = 2.0         # skip LLM for recordings shorter than this
no_speech_threshold = 0.6
min_audio_seconds = 0.3
models_dir = "~/.cache/open_flow/models"
```

Models are stored in `~/.cache/open_flow/models/` and are never committed to the repo.

---

## 📁 Project Structure

```
open-flow/
├── pyproject.toml                  # dependencies and entry point
├── scripts/
│   └── download_models.py          # downloads Whisper + LLM models from HuggingFace
└── src/
    └── open_flow/
        ├── main.py                 # entry point, permission check, launches tray
        ├── tray.py                 # rumps menu-bar app, orchestrates the pipeline
        ├── audio.py                # sounddevice mic capture into in-memory buffer
        ├── hotkey.py               # pynput global push-to-talk listener
        ├── transcribe.py           # faster-whisper wrapper + VAD trim + hallucination filter
        ├── cleanup.py              # llama-cpp-python LLM cleanup (Qwen2.5-3B)
        ├── inject.py               # clipboard swap + Cmd+V text injection
        ├── hud.py                  # PyObjC floating waveform overlay window
        ├── permissions.py          # macOS Accessibility permission check
        └── config.py               # TOML config load/save
```

---

## 🏗️ Architecture

```
[pynput hotkey thread]
       │ press/release
       ▼
[main thread queue]  ←──────────────────────────────────┐
       │                                                 │
       ▼                                                 │
[tray.py — rumps main thread]                           │
   • show/hide HUD                                      │
   • update menu-bar icon + status                      │
   • spawns worker thread on release ──────────────┐    │
                                                   │    │
[audio thread — sounddevice callback]              │    │
   • fills in-memory buffer                        │    │
   • pushes RMS chunks to HUD                      │    │
                                                   ▼    │
                                          [worker thread]
                                             1. VAD trim silence
                                             2. Whisper transcribe
                                             3. LLM cleanup (optional)
                                             4. Clipboard swap + Cmd+V
                                             5. Post status back to main ──┘
```
