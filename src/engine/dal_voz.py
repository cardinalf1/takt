"""
Desert Ant Labs 'Voz' Speech-to-Text Engine
Integrates the official Desert Ant Labs Voz engine (Parakeet TDT, DirectML)
through a supervised Node.js child process, with fallback to local faster-whisper.

Hardening:
- stdout is consumed by a reader thread and every request has a timeout, so a wedged
  Node worker can never freeze the dictation pipeline; it is killed and restarted.
- stderr is drained continuously (an undrained pipe fills at ~64KB and deadlocks the child).
- A dead worker is detected and transparently respawned on the next request.
- Audio is handed to the model as 16 kHz mono PCM16 (the native Parakeet input format).
"""

import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time
from math import gcd
from typing import Optional

import numpy as np
import scipy.signal
import soundfile as sf

from src.core.config import resource_dir

CREATE_NO_WINDOW = 0x08000000
MODEL_SAMPLE_RATE = 16000
READY_TIMEOUT_SEC = 120.0       # first launch downloads/compiles DirectML kernels
REQUEST_TIMEOUT_SEC = 45.0


class VozWorkerError(RuntimeError):
    pass


class DALVozEngine:
    def __init__(
        self,
        backend: str = "voz",
        language: str = "en",
        compute_type: str = "float16",
        whisper_model_path: Optional[str] = None
    ):
        self.backend = backend
        self.language = language
        self.compute_type = compute_type
        self.whisper_model_path = whisper_model_path
        self._is_loaded = False
        self._lock = threading.RLock()          # guards load/unload state
        self._io_lock = threading.Lock()        # serialises requests to the worker
        self._voz_proc: Optional[subprocess.Popen] = None
        self._stdout_q: "queue.Queue[Optional[str]]" = queue.Queue()
        self._whisper_model = None
        self._temp_dir = os.path.join(tempfile.gettempdir(), "Takt")
        os.makedirs(self._temp_dir, exist_ok=True)

    @property
    def is_loaded(self) -> bool:
        with self._lock:
            return self._is_loaded

    # ------------------------------------------------------------------ loading
    def load(self):
        with self._lock:
            if self._is_loaded:
                return

            if self.backend == "voz":
                try:
                    self._load_official_voz()
                except Exception as e:
                    print(f"[STT Engine Notice] Official Voz backend unavailable ({e}). Falling back to local Whisper...")
                    self._kill_worker()
                    self.backend = "whisper"
                    self._load_whisper()
            else:
                self._load_whisper()
            self._is_loaded = True

    def _node_dir(self) -> str:
        if getattr(sys, "frozen", False):
            for base in (resource_dir(), os.path.join(os.path.dirname(sys.executable), "_internal"),
                         os.path.dirname(sys.executable)):
                cand = os.path.join(base, "src", "engine", "voz_node")
                if os.path.exists(cand):
                    return cand
                cand = os.path.join(base, "voz_node")
                if os.path.exists(cand):
                    return cand
            return os.path.join(resource_dir(), "src", "engine", "voz_node")
        return os.path.abspath(os.path.join(os.path.dirname(__file__), "voz_node"))

    def _load_official_voz(self):
        """Spawns the local Node.js worker hosting @desert-ant-labs/voz with DirectML."""
        node_dir = self._node_dir()
        service_file = os.path.join(node_dir, "service.mjs")
        if not os.path.exists(service_file):
            raise FileNotFoundError(f"Voz Node service not found at {service_file}")

        node_bin = os.path.join(node_dir, "bin", "node.exe")
        node_cmd = node_bin if os.path.exists(node_bin) else "node"

        print(f"[STT Engine] Initializing official Desert Ant Labs Voz using '{node_cmd}'...")
        self._stdout_q = queue.Queue()
        proc = subprocess.Popen(
            [node_cmd, "--max-old-space-size=4096", "service.mjs"],
            cwd=node_dir,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=CREATE_NO_WINDOW
        )
        self._voz_proc = proc

        # Dedicated pump threads: never block the pipeline on a raw pipe read
        threading.Thread(target=self._pump_stdout, args=(proc, self._stdout_q), daemon=True, name="Takt-VozOut").start()
        threading.Thread(target=self._pump_stderr, args=(proc,), daemon=True, name="Takt-VozErr").start()

        line = self._read_response(READY_TIMEOUT_SEC)
        try:
            status = json.loads(line)
        except json.JSONDecodeError:
            raise VozWorkerError(f"Voz worker sent invalid ready signal: {line!r}")
        if status.get("status") != "ready":
            raise VozWorkerError(f"Voz initialization error: {status.get('error')}")
        print(f"[STT Engine] Official Desert Ant Labs Voz ready on {status.get('ep', 'gpu')}.")

    @staticmethod
    def _pump_stdout(proc: subprocess.Popen, q: "queue.Queue[Optional[str]]"):
        try:
            for line in proc.stdout:
                line = line.strip()
                if line:
                    q.put(line)
        except Exception:
            pass
        finally:
            q.put(None)  # EOF marker: worker exited

    @staticmethod
    def _pump_stderr(proc: subprocess.Popen):
        try:
            for line in proc.stderr:
                line = line.rstrip()
                if line:
                    print(f"[Voz Worker] {line}")
        except Exception:
            pass

    def _read_response(self, timeout: float) -> str:
        try:
            line = self._stdout_q.get(timeout=timeout)
        except queue.Empty:
            raise VozWorkerError(f"Voz worker did not respond within {timeout:.0f}s")
        if line is None:
            raise VozWorkerError("Voz worker exited unexpectedly")
        return line

    def _kill_worker(self):
        proc, self._voz_proc = self._voz_proc, None
        if proc is None:
            return
        try:
            if proc.stdin:
                try:
                    proc.stdin.close()
                except Exception:
                    pass
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=2.0)
                except subprocess.TimeoutExpired:
                    proc.kill()
        except Exception:
            pass

    def _load_whisper(self):
        """Fallback to local faster-whisper on GPU or CPU."""
        from faster_whisper import WhisperModel
        model_name = self.whisper_model_path or "base.en"
        try:
            if self.compute_type == "float16":
                print(f"[STT Engine] Loading Whisper model '{model_name}' on CUDA...")
                self._whisper_model = WhisperModel(model_name, device="cuda", compute_type="float16")
                dummy = np.zeros(MODEL_SAMPLE_RATE, dtype=np.float32)
                list(self._whisper_model.transcribe(dummy)[0])  # verifies CUDA DLLs are present
            else:
                self._whisper_model = WhisperModel(model_name, device="cpu", compute_type="int8")
        except Exception as e:
            print(f"[STT Engine Notice] CUDA unavailable ({e}), using CPU INT8 fallback...")
            self._whisper_model = WhisperModel(model_name, device="cpu", compute_type="int8")

    # ------------------------------------------------------------ transcription
    @staticmethod
    def _to_model_rate(audio: np.ndarray, sample_rate: int) -> np.ndarray:
        audio = np.asarray(audio, dtype=np.float32).reshape(-1)
        if sample_rate != MODEL_SAMPLE_RATE:
            g = gcd(MODEL_SAMPLE_RATE, int(sample_rate))
            audio = scipy.signal.resample_poly(audio, MODEL_SAMPLE_RATE // g, int(sample_rate) // g).astype(np.float32)
        return np.clip(audio, -1.0, 1.0)

    def transcribe(self, audio: np.ndarray, sample_rate: int = 48000) -> str:
        if audio is None or len(audio) < int(sample_rate * 0.08):
            return ""

        if not self.is_loaded:
            self.load()

        pcm = self._to_model_rate(audio, sample_rate)
        temp_wav = os.path.join(self._temp_dir, f"stt_{os.getpid()}_{int(time.time() * 1000)}.wav")
        try:
            sf.write(temp_wav, pcm, MODEL_SAMPLE_RATE, subtype="PCM_16", format="WAV")

            if self.backend == "voz":
                try:
                    return self._transcribe_voz(temp_wav)
                except VozWorkerError as e:
                    # Worker hung/crashed: restart once and retry this utterance
                    print(f"[STT Engine Warning] {e}. Restarting Voz worker and retrying...")
                    self.unload()
                    self.load()
                    if self.backend == "voz":
                        return self._transcribe_voz(temp_wav)
                    return self._transcribe_whisper(temp_wav)
            return self._transcribe_whisper(temp_wav)
        finally:
            try:
                os.remove(temp_wav)
            except OSError:
                pass

    def _transcribe_voz(self, wav_path: str) -> str:
        with self._io_lock:
            proc = self._voz_proc
            if proc is None or proc.poll() is not None:
                raise VozWorkerError("Voz worker is not running")

            # Discard any stale lines from earlier timed-out requests
            while True:
                try:
                    self._stdout_q.get_nowait()
                except queue.Empty:
                    break

            req = json.dumps({"action": "transcribe", "path": wav_path}) + "\n"
            try:
                proc.stdin.write(req)
                proc.stdin.flush()
            except (OSError, ValueError) as e:
                raise VozWorkerError(f"Could not send request to Voz worker: {e}")

            try:
                res_line = self._read_response(REQUEST_TIMEOUT_SEC)
            except VozWorkerError:
                self._kill_worker()
                raise

        try:
            res = json.loads(res_line)
        except json.JSONDecodeError:
            raise VozWorkerError(f"Malformed Voz response: {res_line[:120]!r}")
        if res.get("status") != "ok":
            raise RuntimeError(f"Voz transcription failure: {res.get('error')}")
        return (res.get("text") or "").strip()

    def _transcribe_whisper(self, wav_path: str) -> str:
        if self._whisper_model is None:
            self._load_whisper()
        segments, _ = self._whisper_model.transcribe(
            wav_path,
            language=self.language,
            vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=200)
        )
        return " ".join(seg.text.strip() for seg in segments).strip()

    def unload(self):
        with self._lock:
            self._kill_worker()
            was_loaded = self._is_loaded
            self._whisper_model = None
            self._is_loaded = False
            if was_loaded:
                print("[STT Engine] STT models unloaded cleanly from memory.")
