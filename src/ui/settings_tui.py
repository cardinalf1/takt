"""
Takt Terminal TUI Settings Utility
Lightweight, keyboard-navigable ANSI terminal interface for quick headless or developer configuration.
"""

import os
import sys
import sounddevice as sd

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.core import config as _core_config


def clear_screen():
    os.system("cls" if os.name == "nt" else "clear")


def load_config():
    return _core_config.load_config()


def save_config(cfg):
    _core_config.save_config(cfg)


def run_tui():
    cfg = load_config()

    while True:
        clear_screen()
        hk = cfg.get("hotkey", {}).get("key", "alt_r").upper()
        mode = cfg.get("hotkey", {}).get("mode", "push_to_talk")
        dev = cfg.get("audio", {}).get("device")
        dev_str = "System Default" if dev is None else f"Device #{dev}"
        ttl = cfg.get("performance", {}).get("idle_eviction_ttl_sec", 180)
        priv = "Enabled" if cfg.get("privacy_shield", {}).get("enabled", False) else "Disabled"
        rec_count = cfg.get("logging", {}).get("max_audio_recordings", 10)
        hud = "Enabled" if cfg.get("ui", {}).get("hud_enabled", True) else "Disabled"
        tray = "Enabled" if cfg.get("ui", {}).get("tray_enabled", True) else "Disabled"

        print("=" * 66)
        print("                 TAKT - TERMINAL CONFIGURATION")
        print("=" * 66)
        print(f" [1] Hotkey Trigger         : {hk} ({mode})")
        print(f" [2] Audio Input Device     : {dev_str}")
        print(f" [3] Floating Pill HUD      : {hud}")
        print(f" [4] System Tray Icon       : {tray}")
        print(f" [5] Privacy Shield         : {priv}")
        print(f" [6] Idle Eviction Sleep    : {ttl}s")
        print(f" [7] Max Audio Recordings   : {rec_count} files")
        print("=" * 66)
        print(" [L] List Audio Devices    [R] Reset Defaults    [Q] Quit")
        print("=" * 66)

        choice = input("\nEnter option [1-7, L, Q]: ").strip().lower()

        if choice == "q":
            break
        elif choice == "1":
            print("\nOptions: 1. Right Alt (alt_r) | 2. Left Alt (alt_l) | 3. Right Ctrl (ctrl_r)")
            k = input("Select [1-3]: ").strip()
            key_map = {"1": "alt_r", "2": "alt_l", "3": "ctrl_r"}
            if k in key_map:
                cfg.setdefault("hotkey", {})["key"] = key_map[k]
                save_config(cfg)
        elif choice == "2":
            idx_in = input("\nEnter device index (or 'default'): ").strip().lower()
            if idx_in == "default" or idx_in == "":
                cfg.setdefault("audio", {})["device"] = None
            else:
                try:
                    cfg.setdefault("audio", {})["device"] = int(idx_in)
                except ValueError:
                    pass
            save_config(cfg)
        elif choice == "3":
            curr = cfg.setdefault("ui", {}).get("hud_enabled", True)
            cfg["ui"]["hud_enabled"] = not curr
            save_config(cfg)
        elif choice == "4":
            curr = cfg.setdefault("ui", {}).get("tray_enabled", True)
            cfg["ui"]["tray_enabled"] = not curr
            save_config(cfg)
        elif choice == "5":
            curr = cfg.setdefault("privacy_shield", {}).get("enabled", False)
            cfg["privacy_shield"]["enabled"] = not curr
            save_config(cfg)
        elif choice == "6":
            t = input("\nEnter idle seconds before sleep (e.g. 60, 180, 300): ").strip()
            try:
                cfg.setdefault("performance", {})["idle_eviction_ttl_sec"] = int(t)
                save_config(cfg)
            except ValueError:
                pass
        elif choice == "7":
            r = input("\nEnter max recordings to retain (5-50): ").strip()
            try:
                cfg.setdefault("logging", {})["max_audio_recordings"] = int(r)
                save_config(cfg)
            except ValueError:
                pass
        elif choice == "l":
            print("\n--- Available Input Devices ---")
            for idx, d in enumerate(sd.query_devices()):
                if d.get("max_input_channels", 0) > 0:
                    print(f"  [{idx}] {d.get('name')}")
            input("\nPress Enter to return...")

if __name__ == "__main__":
    run_tui()
