# Takt

**Fast, private, system-wide voice dictation for Windows 10 & 11.**
Hold a key, talk, release. Clean text appears in whatever app you're using.

Powered by [Desert Ant Labs](https://huggingface.co/desert-ant-labs) models (`Voz`, `Clear`, `Uhm`, `Redact`). Speech recognition and noise cleanup run entirely on your machine, and audio never leaves your PC.

Repo: <https://github.com/cardinalf1/takt>

---

## Quick Start

### Option A: 1-Click Installer (easiest)

1. Download **`Takt-Windows-x64.zip`** from the [latest release](https://github.com/cardinalf1/takt/releases/latest).
2. Extract it and double-click **`TaktSetup.exe`**.
3. Click **Install Takt**. It adds Desktop/Start Menu shortcuts and starts Takt in your system tray.

No Python or Node.js needed. Later updates: open Takt Settings, go to **About**, then **Install update…**.

### Option B: Clone & Run (for developers)

Requires [Python 3.10+](https://www.python.org/downloads/) and [Node.js 18+](https://nodejs.org) (Node is used by the Voz speech engine).

```cmd
git clone https://github.com/cardinalf1/takt.git
cd takt
setup.bat
```

`setup.bat` does everything in one go:

1. Checks for Python 3.10+
2. Creates a local `.venv`
3. Installs `requirements.txt`
4. Runs `scripts/bootstrap.py`, which downloads the Clear noise model (~25 MB), runs `npm install` for the Voz engine, checks your config, and tests your microphone
5. Offers to launch Takt

Start it any time afterwards with `run_takt.bat` (no terminal window; Takt lives in the system tray).

> **Offline or download failed?** Takt still works. It falls back to a lightweight high-pass cleanup instead of the Clear model. Re-run `python scripts/bootstrap.py` when you're online to enable full noise suppression.

---

## Using Takt

| Action | Hotkey |
| :--- | :--- |
| **Dictate (push-to-talk)** | Hold **Right Alt**, speak, release. The text is typed into the focused app. |
| Open Settings | Click the Takt tray icon |

Left Alt is untouched, so your normal shortcuts keep working. You can change the hotkey and switch to toggle mode in Settings.

Takt also:

- Strips filler words ("um", "uh", "like") and supports spoken rollbacks ("scratch that")
- Adapts formatting to what you're typing into: code, chat, or prose
- Can mask API keys, card numbers and other PII before inserting text (Privacy Shield, off by default)

---

## Configuration

Settings are edited from the tray icon's **Settings** window. They're stored in `%APPDATA%\Takt\app_config.yaml`, so updates and reinstalls never overwrite them. The repo ships a clean template at [`config/app_config.yaml`](config/app_config.yaml). To keep everything inside the app folder, create an empty file named `portable` next to the app.

```yaml
hotkey:
  key: alt_r              # push-to-talk key
  mode: push_to_talk      # or: toggle
audio:
  device: null            # null = system default microphone
ui:
  accent_color: '#ffbdd4'
```

### Optional: smarter formatting with a Groq API key

Takt works fully offline with no key. If you add a free [Groq](https://console.groq.com/keys) API key, an LLM polishes punctuation and phrasing for longer dictations. Only the transcribed **text** is sent, never audio.

Pick one:

- **In the app:** Settings, then Formatter, then paste your key.
- **Environment variable** (nothing written to disk):
  ```cmd
  setx GROQ_API_KEY "gsk_your_key_here"
  ```
  Restart Takt afterwards.

Without a key, Takt silently uses the local lightweight formatter. **Never commit your key.** `.gitignore` excludes `.env*` files, and the repo template always has an empty `groq_api_key`.

---

## System Requirements

| | Minimum (CPU) | Recommended (RTX GPU) |
| :--- | :--- | :--- |
| **OS** | Windows 10 20H2+ / Windows 11 (64-bit) | Windows 11 (64-bit) |
| **CPU / RAM** | 4 cores (i5 8th gen / Ryzen 3+), 8 GB | i7 10th gen / Ryzen 7, 16 GB |
| **Disk** | 1.5 GB free | 2 GB free SSD |
| **Latency** | 0.6 - 1.1 s | 0.15 - 0.35 s |
| **Idle usage** | ~72 MB RAM, 0% CPU | ~72 MB RAM, 0% CPU |

Details: [`SYSTEM_REQUIREMENTS.md`](SYSTEM_REQUIREMENTS.md).

---

## Troubleshooting

| Problem | Fix |
| :--- | :--- |
| Nothing is typed | Run `setup.bat` again and check the Voz step; make sure Node.js is installed. |
| No audio / wrong mic | Pick your microphone in Settings. `scripts/bootstrap.py` lists detected devices. |
| Full self-check | `.venv\Scripts\python scripts\verify_system.py` |
| Run the tests | `.venv\Scripts\python tests\test_components.py` |

---

## For Maintainers

Build and release are automated by [`.github/workflows/build-release.yml`](.github/workflows/build-release.yml). Pushing a tag like `v1.0.4` builds `Takt.exe` with PyInstaller, compiles the C# installer/updater/uninstaller, and publishes `Takt-Windows-x64.zip` to GitHub Releases.

```cmd
git tag v1.0.4
git push origin v1.0.4
```

Local build: `pyinstaller Takt.spec --noconfirm`, then `python scripts/sync_dist.py` for the C# tools. `python scripts/package_update.py --version 1.0.4 --notes "..."` creates an update zip for in-app updating.

```
takt/
├── .github/workflows/   # CI: build + release
├── assets/              # icons
├── config/              # app_config.yaml template, disfluencies, jargon
├── models/              # clear-studio.onnx (downloaded by bootstrap)
├── scripts/             # bootstrap, verify, packaging, C# installer sources
├── src/                 # audio, core, engine (Voz/Clear/Uhm/Redact), injector, ui
├── tests/               # component tests
├── setup.bat            # 1-click setup for clones
└── run_takt.bat         # launcher
```

---

Built by Raghav & Desert Ant Labs.
