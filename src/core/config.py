"""
Takt configuration: single source of truth for locating, loading, and saving
app_config.yaml for both source-tree and PyInstaller-frozen runs.

- Settings live in %APPDATA%/Takt/app_config.yaml (or <app_dir>/config in portable mode) so
  updates, rebuilds and reinstalls that replace the install folder never touch them. An
  existing <app_dir>/config/app_config.yaml is migrated there on first load.

- Defaults are always deep-merged underneath the user's file, so a partial or
  stale config can never crash the app with a missing key.
- A corrupt YAML file is quarantined (renamed *.bad) and defaults are used.
- Saves are atomic (write temp + replace) so a crash mid-save can't truncate the file.
"""

import copy
import os
import shutil
import sys
import time
from typing import Any, Dict

import yaml

DEFAULT_CONFIG: Dict[str, Any] = {
    "hotkey": {"key": "alt_r", "mode": "push_to_talk"},
    "audio": {
        "device": None,          # None = system default, str = device name, int = legacy index
        "sample_rate": 48000,
        "channels": 1,
        "buffer_duration_sec": 120.0,
        "trailing_flush_ms": 350,
    },
    "models": {
        "backend": "voz",
        "voz": {"language": "en", "compute_type": "float16"},
        "clear": {"model_path": "models/clear-studio.onnx"},
        "uhm": {"silence_threshold": 0.003, "min_silence_duration_ms": 150},
        "whisper": {"model_path": "base.en", "compute_type": "float16"},
        "formatter": {
            "mode": "lightweight",   # lightweight | ollama | smart_groq | smart_anthropic | smart_openai
            "style": "clean",        # clean | verbatim | bullets
            "groq_api_key": "",
            "groq_model": "qwen/qwen3.8-27b",
            "router": "heuristic",   # heuristic | always_smart | jev | disabled
            "typesafe_api_key": "",
            "typesafe_endpoint": "https://api.typesafe.ai/v1/systemone",
            "anthropic_api_key": "",
            "anthropic_model": "claude-3-5-sonnet-latest",
            "openai_api_key": "",
            "openai_model": "gpt-4o-mini",
            "ollama_endpoint": "http://127.0.0.1:11434",
            "ollama_model": "qwen2.5:1.5b",
        },
    },
    "privacy_shield": {
        "enabled": False,
        "mask_char": "*",
        "rules": ["credit_card", "phone_number", "email", "api_key", "ssn"],
    },
    "logging": {
        "enabled": True,
        "log_dir": "logs",
        "save_audio_recordings": True,
        "max_audio_recordings": 10,
    },
    "injection": {"method": "direct_unicode", "restore_delay_ms": 1500},
    "performance": {"idle_eviction_ttl_sec": 180, "enable_cuda": True},
    "ui": {
        "hud_enabled": True,
        "tray_enabled": True,
        "accent_color": "#ffbdd4",
        "bottom_offset": 24,
    },
}


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def app_dir() -> str:
    """Directory containing Takt.exe (frozen) or the project root (source)."""
    if is_frozen():
        return os.path.dirname(sys.executable)
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def resource_dir() -> str:
    """Directory holding bundled read-only resources (PyInstaller _MEIPASS or project root)."""
    if is_frozen():
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return app_dir()


PORTABLE_MARKERS = ("portable", "takt_portable.flag")


def is_portable() -> bool:
    """Portable mode: a marker file next to the app keeps settings inside the app folder."""
    return any(os.path.exists(os.path.join(app_dir(), m)) for m in PORTABLE_MARKERS)


def _install_config_path() -> str:
    """Legacy/shipped location inside the install folder (replaced on updates and rebuilds)."""
    return os.path.join(app_dir(), "config", "app_config.yaml")


def config_path() -> str:
    """Canonical writable config location, which survives updates, rebuilds and reinstalls.

    Portable mode: <app_dir>/config/app_config.yaml. Otherwise %APPDATA%/Takt/app_config.yaml.
    """
    if is_portable():
        return _install_config_path()
    base = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Roaming")
    return os.path.join(base, "Takt", "app_config.yaml")


def _bundled_config_path() -> str:
    return os.path.join(resource_dir(), "config", "app_config.yaml")


def _migrate_legacy_config() -> None:
    """One-time copy of an existing <app_dir>/config/app_config.yaml to the user config location."""
    dst = config_path()
    src = _install_config_path()
    if os.path.exists(dst) or not os.path.isfile(src):
        return
    try:
        with open(src, "r", encoding="utf-8") as f:
            if not isinstance(yaml.safe_load(f), dict):
                return
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        tmp = f"{dst}.tmp"
        shutil.copy2(src, tmp)
        os.replace(tmp, dst)
        print(f"[Config] Migrated settings from {src} to {dst}")
    except Exception as e:
        print(f"[Config Warning] Could not migrate settings from {src}: {e}")


def deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def load_config() -> Dict[str, Any]:
    user_cfg: Dict[str, Any] = {}
    _migrate_legacy_config()
    # Order: user/portable config -> install-folder config -> bundled defaults.
    for path in (config_path(), _install_config_path(), _bundled_config_path()):
        if not os.path.exists(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            if isinstance(data, dict):
                user_cfg = data
                break
            raise ValueError("top-level YAML value is not a mapping")
        except Exception as e:
            print(f"[Config Warning] Could not parse {path}: {e}")
            try:
                os.replace(path, f"{path}.bad-{int(time.time())}")
                print("[Config Warning] Corrupt config quarantined; using defaults.")
            except Exception:
                pass
    cfg = deep_merge(DEFAULT_CONFIG, user_cfg)
    fmt = cfg["models"]["formatter"]
    if not str(fmt.get("groq_api_key") or "").strip():
        fmt["groq_api_key"] = os.environ.get("GROQ_API_KEY", "")
    return cfg


def save_config(cfg: Dict[str, Any]) -> None:
    path = config_path()
    # Never persist a key that only came from the GROQ_API_KEY environment variable.
    env_key = os.environ.get("GROQ_API_KEY", "")
    fmt = cfg.get("models", {}).get("formatter", {})
    if env_key and fmt.get("groq_api_key") == env_key:
        cfg = copy.deepcopy(cfg)
        cfg["models"]["formatter"]["groq_api_key"] = ""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
    os.replace(tmp, path)


def config_mtime() -> float:
    try:
        return os.path.getmtime(config_path())
    except OSError:
        return 0.0
