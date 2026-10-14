import os
import sys
import time
import yaml
import soundfile as sf
import scipy.signal
import numpy as np

# Ensure project root in sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.core.pipeline import TaktPipeline
from src.engine.dal_clear import DALClearEngine
from src.engine.dal_uhm import DALUhmEngine
from src.engine.dal_voz import DALVozEngine
from src.engine.formatter import ContextualFormatter
from src.core.window_adapter import WindowContextAdapter
from src.engine.dal_redact import DALRedactEngine

def generate_torture_audio(clean_audio_16k: np.ndarray) -> np.ndarray:
    """
    Creates a brutal acoustic environment:
    - 60Hz + 120Hz electrical AC ground-loop hum
    - Mechanical keyboard switch high-frequency clicks (3.5kHz transient impulses)
    - Simulated room boundary reflections (short-delay reverberation)
    - Multi-speaker conversational babble / pink noise floor
    """
    sr = 16000
    corrupted = clean_audio_16k.copy()
    length = len(corrupted)
    t = np.arange(length) / sr

    # 1. 60Hz + 120Hz AC Hum
    hum = 0.05 * np.sin(2 * np.pi * 60 * t) + 0.03 * np.sin(2 * np.pi * 120 * t)
    corrupted += hum

    # 2. Pink noise / background babble
    noise = np.random.normal(0, 0.04, length)
    corrupted += noise

    # 3. Mechanical keyboard switch click impulses (15 random sharp clicks)
    for _ in range(15):
        click_idx = np.random.randint(1000, length - 1000)
        click_len = int(0.008 * sr) # 8ms click transient
        click_t = np.arange(click_len) / sr
        click_wave = 0.25 * np.sin(2 * np.pi * 3500 * click_t) * np.exp(-click_t / 0.002)
        corrupted[click_idx : click_idx + click_len] += click_wave

    # 4. Room reverberation (comb echo filter)
    reverb_delay = int(0.045 * sr) # 45ms reflection
    corrupted[reverb_delay:] += 0.35 * corrupted[:-reverb_delay]

    return corrupted.astype(np.float32)

def run_stress_test():
    print("=" * 75)
    print("   TAKT GAUNTLET: ACOUSTIC TORTURE & SYNTACTIC STRESS TEST")
    print("=" * 75)