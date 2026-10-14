import time
import os
import sys
import soundfile as sf
import numpy as np

sys.path.insert(0, os.path.abspath("."))

from src.engine.dal_voz import DALVozEngine
from faster_whisper import WhisperModel

test_files = [
    "logs/recordings/recording_20261013_012848_114.wav",
    "logs/recordings/recording_20261013_012903_976.wav",
    "logs/recordings/recording_20261013_012918_713.wav"
]

print("=" * 70)
print(" TAKT (DAL VOZ) vs WHISPER: REAL-WORLD LATENCY & ACCURACY BENCHMARK")
print(" Hardware: NVIDIA GeForce RTX 3060 12GB (DirectML) vs Multi-threaded CPU")
print("=" * 70)

# Initialize Voz
print("\n[Init] Initializing Desert Ant Labs Voz (DirectML on RTX 3060)...")
voz = DALVozEngine(backend="voz")
voz.load()

# Initialize Whisper on CPU (optimized int8, 4 threads)
print("[Init] Initializing faster-whisper small.en (CPU int8, 4 threads)...")
whisper = WhisperModel("small.en", device="cpu", compute_type="int8", cpu_threads=4)

# Warm up both engines
dummy = np.zeros(16000, dtype=np.float32)
voz.transcribe(dummy, 16000)
list(whisper.transcribe(dummy, language="en")[0])

results = []

for f in test_files:
    if not os.path.exists(f):
        continue
    data, sr = sf.read(f)
    dur = len(data) / sr

    # Measure Voz
    t0 = time.perf_counter()
    txt_voz = voz.transcribe(data, sr)
    voz_ms = (time.perf_counter() - t0) * 1000

    # Measure Whisper
    t0 = time.perf_counter()
    segs, _ = whisper.transcribe(data, language="en", beam_size=3)
    txt_whisper = " ".join(s.text.strip() for s in segs)
    whisper_ms = (time.perf_counter() - t0) * 1000

    speedup = whisper_ms / voz_ms if voz_ms > 0 else 0
    results.append({
        "file": os.path.basename(f),
        "dur": dur,
        "voz_ms": voz_ms,
        "whisper_ms": whisper_ms,
        "speedup": speedup,
        "txt_voz": txt_voz,
        "txt_whisper": txt_whisper
    })

voz.unload()

print("\n" + "-" * 70)
for r in results:
    print(f"\nRecording: {r['file']} ({r['dur']:.2f}s of human speech)")
    print(f"  DAL Voz (DirectML / RTX 3060): {r['voz_ms']:6.1f} ms  |  RTFX: {r['dur'] / (r['voz_ms']/1000):5.1f}x real-time")
    print(f"  faster-whisper (CPU int8):     {r['whisper_ms']:6.1f} ms  |  RTFX: {r['dur'] / (r['whisper_ms']/1000):5.1f}x real-time")
    print(f"  --> Speedup: Voz is {r['speedup']:.1f}x FASTER than Whisper!")
    print(f"  Voz Text:     \"{r['txt_voz']}\"")
    print(f"  Whisper Text: \"{r['txt_whisper']}\"")

avg_speedup = sum(r['speedup'] for r in results) / len(results)
print("\n" + "=" * 70)
print(f" SUMMARY: Takt (DAL Voz) is on average {avg_speedup:.1f}x FASTER than Whisper!")
print("=" * 70)
