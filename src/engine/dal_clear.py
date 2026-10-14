"""
Desert Ant Labs 'Clear' Studio ONNX Audio Enhancement Engine
Speech dereverberation / noise removal stage.

The shipped clear-studio.onnx is a *spectral* (DeepFilterNet-style) network whose inputs are
STFT / ERB feature tensors, not a raw waveform. Feeding it a waveform always raises, which the
previous implementation swallowed silently on every utterance. This engine now inspects the model
at load time:

- waveform-in / waveform-out models are run directly (chunked), and
- spectral models are detected, reported once in the log, and bypassed (passthrough) so no
  latency or memory is wasted on a stage that cannot run.

In every case a lightweight 80 Hz high-pass filter removes DC offset and low-frequency rumble.
"""

import os
import threading
from typing import Optional

import numpy as np
import onnxruntime as ort
import scipy.signal

from src.core.config import resource_dir

HPF_CUTOFF_HZ = 80.0


class DALClearEngine:
    def __init__(self, model_path: str = "models/clear-studio.onnx"):
        if not os.path.isabs(model_path):
            self.model_path = os.path.join(resource_dir(), model_path)
        else:
            self.model_path = model_path

        self.session: Optional[ort.InferenceSession] = None
        self.passthrough = False
        self._is_loaded = False
        self._warned = False
        self._lock = threading.Lock()
        self._hpf_cache = {}

    @property
    def is_loaded(self) -> bool:
        with self._lock:
            return self._is_loaded

    def load(self):
        with self._lock:
            if self._is_loaded:
                return

            if not os.path.exists(self.model_path):
                print(f"[Audio Engine Warning] DAL Clear model not found at {self.model_path}; using DSP-only cleanup.")
                self.passthrough = True
                self._is_loaded = True
                return

            opts = ort.SessionOptions()
            opts.intra_op_num_threads = 4
            opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL

            try:
                session = ort.InferenceSession(self.model_path, sess_options=opts, providers=["CPUExecutionProvider"])
                inputs = session.get_inputs()
                is_waveform = len(inputs) == 1 and len(inputs[0].shape) in (2, 3)
                if is_waveform:
                    self.session = session
                    self.passthrough = False
                    print("[Audio Engine] DAL Clear Studio ONNX loaded cleanly.")
                else:
                    names = ", ".join(i.name for i in inputs)
                    print(f"[Audio Engine] DAL Clear model is spectral (inputs: {names}); "
                          f"waveform path bypassed, using high-pass cleanup only.")
                    self.session = None
                    self.passthrough = True
                    del session
                self._is_loaded = True
            except Exception as e:
                print(f"[Audio Engine Warning] Failed to initialize ONNX session: {e}. Using DSP-only cleanup.")
                self.session = None
                self.passthrough = True
                self._is_loaded = True

    def _highpass(self, audio: np.ndarray, sample_rate: int) -> np.ndarray:
        sos = self._hpf_cache.get(sample_rate)
        if sos is None:
            sos = scipy.signal.butter(2, HPF_CUTOFF_HZ, btype="highpass", fs=sample_rate, output="sos")
            self._hpf_cache[sample_rate] = sos
        return scipy.signal.sosfilt(sos, audio).astype(np.float32)

    def enhance(self, audio: np.ndarray, sample_rate: int = 48000) -> np.ndarray:
        """Returns cleaned audio; always falls back to the high-passed input instead of raising."""
        if audio is None or len(audio) == 0:
            return audio

        cleaned = self._highpass(np.asarray(audio, dtype=np.float32), sample_rate)

        with self._lock:
            session = self.session
            if self.passthrough or session is None:
                return cleaned

        try:
            tensor = cleaned[None, :]
            out = session.run(None, {session.get_inputs()[0].name: tensor})[0].reshape(-1).astype(np.float32)
            if out.shape[0] != cleaned.shape[0] or not np.all(np.isfinite(out)):
                raise ValueError(f"unexpected model output ({out.shape} vs {cleaned.shape})")
            return out
        except Exception as e:
            if not self._warned:
                self._warned = True
                print(f"[Audio Engine Warning] DAL Clear inference failed ({e}); passing audio through.")
            self.passthrough = True
            return cleaned

    def unload(self):
        with self._lock:
            if not self._is_loaded:
                return
            self.session = None
            self._is_loaded = False
            self.passthrough = False
            print("[Audio Engine] DAL Clear Studio ONNX unloaded cleanly from memory.")
