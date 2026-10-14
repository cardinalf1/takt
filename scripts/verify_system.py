import time
import os
import sys
import yaml
import soundfile as sf
import scipy.signal
import numpy as np
import psutil

# Ensure project root in sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

print("=" * 70)
print(" TAKT SYSTEM-WIDE END-TO-END VERIFICATION & BENCHMARK")
print("=" * 70)

# Load App Config
cfg_path = os.path.join(PROJECT_ROOT, "config", "app_config.yaml")
with open(cfg_path, "r", encoding="utf-8") as f:
    cfg = yaml.safe_load(f)

from src.core.pipeline import TaktPipeline
from src.core.hook import GlobalKeyboardHook

# 1. Pipeline Initialization
print("\n[1/7] Initializing Takt Full Pipeline...")
t_init0 = time.time()
pipeline = TaktPipeline(cfg)
t_init = (time.time() - t_init0) * 1000
print(f" -> Pipeline initialized in {t_init:.1f}ms")
print(f" -> STT Engine: Official Desert Ant Labs Voz (Backend: {pipeline.voz_engine.backend})")
print(f" -> Audio Target Sample Rate: {pipeline.capture.target_sample_rate}Hz")
print(f" -> Hotkey: {cfg.get('hotkey', {}).get('key', 'alt_r').upper()}")