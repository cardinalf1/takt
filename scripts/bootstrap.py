"""
Takt bootstrap: prepares a fresh clone so Takt runs out of the box.

    python scripts/bootstrap.py

Steps (each one is non-fatal except the Python version check):
  1. Verify Python >= 3.10
  2. Download models/clear-studio.onnx if missing (falls back to DSP high-pass cleanup if offline)
  3. Install the Voz speech engine's Node dependencies (src/engine/voz_node)
  4. Make sure config/app_config.yaml exists and carries no API key
  5. Check that a microphone is available via sounddevice
"""

import os
import shutil
import subprocess
import sys
import urllib.request

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
MIN_PYTHON = (3, 10)

CLEAR_URL = "https://huggingface.co/desert-ant-labs/clear/resolve/main/clear-studio.onnx"
CLEAR_PATH = os.path.join(PROJECT_ROOT, "models", "clear-studio.onnx")
VOZ_NODE_DIR = os.path.join(PROJECT_ROOT, "src", "engine", "voz_node")
CONFIG_PATH = os.path.join(PROJECT_ROOT, "config", "app_config.yaml")

TEMPLATE_CONFIG = """\
hotkey:
  key: alt_r
  mode: push_to_talk
audio:
  device: null
  sample_rate: 48000
  channels: 1
  buffer_duration_sec: 120.0
  trailing_flush_ms: 350
models:
  backend: voz
  voz:
    language: en
    compute_type: float16
  clear:
    model_path: models/clear-studio.onnx
  formatter:
    mode: smart_groq
    style: clean
    groq_api_key: ''   # optional; or set the GROQ_API_KEY environment variable
    router: always_smart
ui:
  hud_enabled: true
  tray_enabled: true
  accent_color: '#ffbdd4'
"""


def ok(msg):
    print(f"  [ OK ] {msg}")


def warn(msg):
    print(f"  [WARN] {msg}")


def step(n, title):
    print(f"\n[{n}/5] {title}")


# --------------------------------------------------------------------------- 1. python
def check_python() -> bool:
    step(1, "Checking Python version")
    v = sys.version_info
    if (v.major, v.minor) < MIN_PYTHON:
        print(f"  [FAIL] Python {v.major}.{v.minor} found; Takt needs Python "
              f"{MIN_PYTHON[0]}.{MIN_PYTHON[1]}+. Get it from https://www.python.org/downloads/")
        return False
    ok(f"Python {v.major}.{v.minor}.{v.micro}")
    return True


# --------------------------------------------------------------------------- 2. clear model
_last_pct = -1


def _progress(done: int, total: int) -> None:
    global _last_pct
    if total > 0:
        pct = done * 100 // total
        if pct == _last_pct and done != total:
            return
        _last_pct = pct
        bar = "#" * (pct // 4) + "-" * (25 - pct // 4)
        sys.stdout.write(f"\r  [{bar}] {pct:3d}%  {done / 1e6:6.1f}/{total / 1e6:.1f} MB")
    else:
        sys.stdout.write(f"\r  {done / 1e6:6.1f} MB")
    sys.stdout.flush()


def ensure_clear_model() -> None:
    step(2, "Checking Clear noise-suppression model")
    if os.path.isfile(CLEAR_PATH) and os.path.getsize(CLEAR_PATH) > 1_000_000:
        ok(f"Found {os.path.relpath(CLEAR_PATH, PROJECT_ROOT)}")
        return

    print("  models/clear-studio.onnx is missing; downloading from Desert Ant Labs (~25 MB)...")
    os.makedirs(os.path.dirname(CLEAR_PATH), exist_ok=True)
    tmp = CLEAR_PATH + ".part"
    try:
        req = urllib.request.Request(CLEAR_URL, headers={"User-Agent": "Takt-bootstrap"})
        with urllib.request.urlopen(req, timeout=30) as resp, open(tmp, "wb") as out:
            total = int(resp.headers.get("Content-Length") or 0)
            done = 0
            while True:
                chunk = resp.read(1 << 16)
                if not chunk:
                    break
                out.write(chunk)
                done += len(chunk)
                _progress(done, total)
        print()
        if total and done != total:
            raise IOError(f"incomplete download ({done} of {total} bytes)")
        os.replace(tmp, CLEAR_PATH)
        ok("Downloaded clear-studio.onnx")
    except Exception as e:
        print()
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass
        warn(f"Could not download the Clear model ({e}).")
        warn("Takt will still work: it runs in DSP high-pass cleanup mode "
             "(slightly less noise suppression).")
        warn(f"To enable full cleanup later, re-run this script or download {CLEAR_URL} "
             "into the models/ folder.")


# --------------------------------------------------------------------------- 3. voz node
def ensure_voz_node() -> None:
    step(3, "Checking Voz speech engine (Node.js dependencies)")
    if not os.path.isfile(os.path.join(VOZ_NODE_DIR, "package.json")):
        warn("src/engine/voz_node/package.json not found; skipping.")
        return
    if os.path.isdir(os.path.join(VOZ_NODE_DIR, "node_modules")):
        ok("node_modules already installed")
        return

    npm = shutil.which("npm.cmd") or shutil.which("npm")
    if not npm:
        warn("npm not found. Install Node.js 18+ from https://nodejs.org, then re-run this script.")
        warn("Until then the Voz speech engine cannot start.")
        return

    print("  Running 'npm install' in src/engine/voz_node (first run can take a minute)...")
    try:
        res = subprocess.run([npm, "install", "--no-audit", "--no-fund"], cwd=VOZ_NODE_DIR)
        if res.returncode != 0:
            warn(f"npm install failed (exit code {res.returncode}). Check your network and retry.")
            return
        ok("Installed Node dependencies")
    except Exception as e:
        warn(f"npm install could not run: {e}")


# --------------------------------------------------------------------------- 4. config
def ensure_config() -> None:
    step(4, "Checking config/app_config.yaml")
    if not os.path.isfile(CONFIG_PATH):
        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            f.write(TEMPLATE_CONFIG)
        ok("Created a clean config template")
        return

    try:
        import yaml
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if not isinstance(data, dict):
            raise ValueError("top-level YAML value is not a mapping")
    except ImportError:
        ok("Config present (PyYAML not installed yet, skipping validation)")
        return
    except Exception as e:
        backup = CONFIG_PATH + ".bad"
        os.replace(CONFIG_PATH, backup)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            f.write(TEMPLATE_CONFIG)
        warn(f"Config was unreadable ({e}); moved to {os.path.basename(backup)} and recreated.")
        return

    key = str((data.get("models", {}).get("formatter", {}) or {}).get("groq_api_key") or "").strip()
    if key:
        ok("Config present (contains a Groq API key; do not commit it to git)")
    else:
        ok("Config present (no API key; add one in Takt Settings or via GROQ_API_KEY)")


# --------------------------------------------------------------------------- 5. audio
def check_audio() -> None:
    step(5, "Checking audio input devices")
    try:
        import sounddevice as sd
        inputs = [d for d in sd.query_devices() if d.get("max_input_channels", 0) > 0]
        if not inputs:
            warn("No microphone detected. Plug one in or enable it in Windows Sound settings.")
            return
        try:
            default = sd.query_devices(kind="input")["name"]
        except Exception:
            default = inputs[0]["name"]
        ok(f"{len(inputs)} input device(s) found; default: {default}")
    except ImportError:
        warn("sounddevice is not installed; run: pip install -r requirements.txt")
    except Exception as e:
        warn(f"Could not query audio devices: {e}")


def main() -> int:
    print("=" * 60)
    print(" Takt bootstrap")
    print("=" * 60)
    if not check_python():
        return 1
    ensure_clear_model()
    ensure_voz_node()
    ensure_config()
    check_audio()
    print("\nBootstrap finished. Launch Takt with run_takt.bat (hold Right Alt to dictate).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
