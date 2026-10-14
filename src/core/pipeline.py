"""
Takt Pipeline Orchestrator
Coordinates:
1. Low-latency audio capture with dead-microphone detection & recovery
2. Level normalisation for quiet microphones
3. Desert Ant Labs 'Clear' cleanup (high-pass + optional neural enhancement)
4. Desert Ant Labs 'Uhm' adaptive acoustic gate & disfluency / voice rollback engine
5. Desert Ant Labs 'Voz' Parakeet TDT neural transcription (DirectML)
6. Context-aware window adapter & punctuation formatting (lightweight or Ollama)
7. Desert Ant Labs 'Redact' privacy shield
8. Win32 Unicode injection
9. Persistent dictation history & rolling audio archives
10. Floating pill HUD

Failure handling: every stage is isolated; any exception in a dictation cycle is logged with a
traceback, shown on the HUD as a short notice, and the pipeline always returns to IDLE.
"""

import ctypes
import gc
import threading
import time
import traceback
from typing import Any, Dict, List, Optional

import numpy as np

from src.audio.capture import AudioCaptureManager, DEAD_PEAK_THRESHOLD
from src.core.logger import DictationLogger
from src.core.state import AppState, StateManager
from src.core.window_adapter import WindowContextAdapter
from src.engine.dal_clear import DALClearEngine
from src.engine.dal_redact import DALRedactEngine
from src.engine.dal_uhm import DALUhmEngine
from src.engine.dal_voz import DALVozEngine
from src.engine.formatter import ContextualFormatter
from src.injector.clipboard import ClipboardInjector
from src.ui.hud import TaktHUD

MIN_RECORDING_SEC = 0.25        # shorter taps are accidental key presses
MIN_SPEECH_SEC = 0.12           # shorter gated audio contains no usable speech
TARGET_PEAK = 0.6               # normalisation target
MAX_GAIN = 24.0                 # ~27 dB of make-up gain for quiet microphones
STUCK_STATE_TIMEOUT_SEC = 120.0


class TaktPipeline:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.state_mgr = StateManager()
        self._press_lock = threading.Lock()
        self._consecutive_dead = 0

        # 0. Floating pill HUD
        ui_cfg = config.get("ui", {})
        self.hud_enabled = ui_cfg.get("hud_enabled", True)
        self.hud: Optional[TaktHUD] = None
        if self.hud_enabled:
            try:
                self.hud = TaktHUD(
                    accent_color=ui_cfg.get("accent_color", "#ffbdd4"),
                    bottom_offset=ui_cfg.get("bottom_offset", 24)
                )
            except Exception as e:
                print(f"[HUD Error] Could not create HUD: {e}")
                traceback.print_exc()

        # 1. Dictation history logger & audio archives
        log_cfg = config.get("logging", {})
        self.logger = DictationLogger(
            log_dir=log_cfg.get("log_dir", "logs"),
            enabled=log_cfg.get("enabled", True),
            save_audio=log_cfg.get("save_audio_recordings", log_cfg.get("save_audio", True)),
            max_audio_recordings=log_cfg.get("max_audio_recordings", 10)
        )

        audio_cfg = config.get("audio", {})
        models_cfg = config.get("models", {})

        # 2. Audio capture engine
        self.capture = AudioCaptureManager(
            target_sample_rate=audio_cfg.get("sample_rate", 48000),
            channels=audio_cfg.get("channels", 1),
            device_index=audio_cfg.get("device", None),
            trailing_flush_ms=audio_cfg.get("trailing_flush_ms", 350),
            buffer_duration_sec=audio_cfg.get("buffer_duration_sec", 120.0),
            level_callback=self._on_audio_level
        )

        # 3. DAL Clear
        clear_cfg = models_cfg.get("clear", {})
        self.clear_engine = DALClearEngine(model_path=clear_cfg.get("model_path", "models/clear-studio.onnx"))

        # 4. DAL Uhm
        uhm_cfg = models_cfg.get("uhm", {})
        self.uhm_engine = DALUhmEngine(
            silence_threshold=uhm_cfg.get("silence_threshold", 0.003),
            min_silence_duration_ms=uhm_cfg.get("min_silence_duration_ms", 150),
            trailing_pad_ms=uhm_cfg.get("trailing_pad_ms", 400),
            taxonomy_path=uhm_cfg.get("taxonomy_path", None)
        )

        # 5. DAL Voz STT
        voz_cfg = models_cfg.get("voz", {})
        perf_cfg = config.get("performance", {})
        self.voz_engine = DALVozEngine(
            backend=models_cfg.get("backend", "voz"),
            language=voz_cfg.get("language", "en"),
            compute_type=voz_cfg.get("compute_type", "float16"),
            whisper_model_path=models_cfg.get("whisper", {}).get("model_path")
        )

        # 6. Window context adapter
        self.window_adapter = WindowContextAdapter()

        # 7. Privacy shield
        redact_cfg = config.get("privacy_shield", {})
        self.redact_engine = DALRedactEngine(
            enabled=redact_cfg.get("enabled", False),
            mask_char=redact_cfg.get("mask_char", "*"),
            rules=redact_cfg.get("rules", ["credit_card", "phone_number", "email", "api_key", "ssn"])
        )

        # 8. Formatter (lightweight rules or local Ollama)
        fmt_cfg = models_cfg.get("formatter", {})
        self.formatter = ContextualFormatter(
            mode=fmt_cfg.get("mode", "lightweight"),
            ollama_endpoint=fmt_cfg.get("ollama_endpoint", "http://127.0.0.1:11434"),
            model_name=fmt_cfg.get("ollama_model", "qwen2.5:1.5b"),
            **{k: v for k, v in fmt_cfg.items() if k not in ("mode", "ollama_endpoint", "ollama_model")},
        )

        # 9. Injector
        inj_cfg = config.get("injection", {})
        self.injector = ClipboardInjector(
            method=inj_cfg.get("method", "direct_unicode"),
            restore_delay_ms=inj_cfg.get("restore_delay_ms", 1500)
        )

        # Performance & TTL eviction
        self.ttl_sec = perf_cfg.get("idle_eviction_ttl_sec", 180)
        self._is_sleeping = False
        self._stop_watchdog = threading.Event()
        self._watchdog_thread = threading.Thread(target=self._idle_watchdog, daemon=True, name="Takt-IdleWatchdog")
        self._watchdog_thread.start()

        # Warm the models in the background so the very first dictation is fast
        threading.Thread(target=self._prewarm, daemon=True, name="Takt-Prewarm").start()

    # ----------------------------------------------------------------- helpers
    def _hud(self, method: str, *args):
        """Calls a HUD method, never letting a UI problem break dictation."""
        if self.hud is None or not self.hud_enabled:
            return
        try:
            getattr(self.hud, method)(*args)
        except Exception as e:
            print(f"[HUD Notice] {method} failed: {e}")

    def _on_audio_level(self, rms: float, bands: Optional[List[float]] = None):
        self._hud("update_levels", rms, bands)

    def _prewarm(self):
        try:
            if not self.clear_engine.is_loaded:
                self.clear_engine.load()
            if not self.voz_engine.is_loaded:
                self.voz_engine.load()
        except Exception as e:
            print(f"[Pipeline Warning] Model pre-warm failed: {e}")

    def apply_config(self, cfg: Dict[str, Any]):
        """Hot-applies settings changes without a restart."""
        try:
            ui = cfg.get("ui", {})
            self.hud_enabled = ui.get("hud_enabled", True)
            if self.hud is None and self.hud_enabled:
                self.hud = TaktHUD(
                    accent_color=ui.get("accent_color", "#ffbdd4"),
                    bottom_offset=ui.get("bottom_offset", 24)
                )
            if self.hud is not None:
                self._hud("set_accent_color", ui.get("accent_color", "#ffbdd4"))
                self._hud("set_bottom_offset", ui.get("bottom_offset", 24))

            self.ttl_sec = cfg.get("performance", {}).get("idle_eviction_ttl_sec", self.ttl_sec)

            priv = cfg.get("privacy_shield", {})
            self.redact_engine.enabled = bool(priv.get("enabled", False))

            fmt = cfg.get("models", {}).get("formatter", {})
            self.formatter.mode = fmt.get("mode", self.formatter.mode)
            self.formatter.ollama_endpoint = fmt.get("ollama_endpoint", self.formatter.ollama_endpoint)
            self.formatter.model_name = fmt.get("ollama_model", self.formatter.model_name)
            for k in ("style", "groq_api_key", "groq_model", "anthropic_api_key",
                      "anthropic_model", "openai_api_key", "openai_model", "router",
                      "typesafe_api_key", "typesafe_endpoint"):
                if k in fmt:
                    setattr(self.formatter, k, fmt[k])

            new_dev = cfg.get("audio", {}).get("device", None)
            if new_dev != self.capture.device_spec and self.state_mgr.current == AppState.IDLE:
                threading.Thread(target=self.capture.set_device, args=(new_dev,), daemon=True,
                                 name="Takt-AudioSwitch").start()
        except Exception as e:
            print(f"[Config Error] Could not apply settings: {e}")
            traceback.print_exc()

    # ------------------------------------------------------------ hotkey events
    def handle_press(self):
        """Called when the hotkey is pressed down."""
        with self._press_lock:
            if self.state_mgr.current != AppState.IDLE:
                print("[Pipeline] Busy with previous dictation; hotkey press ignored.")
                return
            self._is_sleeping = False
            self.state_mgr.transition_to(AppState.RECORDING)
            print("\n[Pipeline] Dictation recording started...")

            self._hud("show_recording")
            try:
                self.capture.start_recording()
            except Exception as e:
                print(f"[Pipeline Error] Could not start recording: {e}")
                traceback.print_exc()
                self._hud("show_notice", "Microphone unavailable")
                self.state_mgr.transition_to(AppState.IDLE)
                return

        # Pre-warm engines while the user speaks if they were evicted
        if not self.clear_engine.is_loaded or not self.voz_engine.is_loaded:
            threading.Thread(target=self._prewarm, daemon=True, name="Takt-Prewarm").start()

    def handle_release(self):
        """Called when the hotkey is released."""
        with self._press_lock:
            if self.state_mgr.current != AppState.RECORDING:
                return
            self.state_mgr.transition_to(AppState.PROCESSING)
            print("[Pipeline] Processing speech buffer...")
            self._hud("show_processing")

            try:
                raw_audio = self.capture.stop_recording()
            except Exception as e:
                print(f"[Pipeline Error] stop_recording failed: {e}")
                traceback.print_exc()
                raw_audio = np.zeros(0, dtype=np.float32)

        threading.Thread(target=self._process_audio_async, args=(raw_audio,), daemon=True,
                         name="Takt-Process").start()

    # --------------------------------------------------------------- processing
    def _handle_dead_signal(self, duration_sec: float):
        self._consecutive_dead += 1
        dev = self.capture.device_name
        if self._consecutive_dead == 1:
            print(f"[Pipeline] No audio signal from '{dev}' (peak {self.capture.last_peak:.5f}).")
            self._hud("show_notice", "No mic signal - check input device")
            return

        new_dev = self.capture.handle_dead_signal()
        if new_dev:
            print(f"[Pipeline] Switched microphone '{dev}' -> '{new_dev}'.")
            self._hud("show_notice", f"Switched mic - try again")
        else:
            print("[Pipeline] No working microphone found. Check Windows Sound > Input settings.")
            self._hud("show_notice", "No working microphone found")
        self._consecutive_dead = 0

    def _process_audio_async(self, raw_audio: np.ndarray):
        """Full execution pipeline running in a dedicated worker thread."""
        try:
            sr = self.capture.target_sample_rate
            if len(raw_audio) == 0:
                print("[Pipeline] Empty audio buffer detected.")
                self._hud("show_notice", "No audio captured")
                return

            duration_sec = len(raw_audio) / sr
            peak = float(np.max(np.abs(raw_audio)))
            rms = float(np.sqrt(np.mean(raw_audio * raw_audio)))
            print(f"[Audio] Captured {duration_sec:.2f}s (RMS: {rms:.4f}, Peak: {peak:.4f}) "
                  f"from '{self.capture.device_name}'")

            if duration_sec < MIN_RECORDING_SEC:
                print("[Pipeline] Recording too short; treating as accidental tap.")
                self._hud("hide")
                return

            # Dead microphone: electrically silent capture (virtual device without a source,
            # Bluetooth headset not in call profile, muted endpoint, ...)
            if peak < DEAD_PEAK_THRESHOLD:
                self._handle_dead_signal(duration_sec)
                return
            self._consecutive_dead = 0

            # Make-up gain for quiet microphones so thresholds and the model see a usable level
            if peak < TARGET_PEAK:
                gain = min(MAX_GAIN, TARGET_PEAK / peak)
                raw_audio = np.clip(raw_audio * gain, -1.0, 1.0).astype(np.float32)
                print(f"[Audio] Applied {20 * np.log10(gain):.1f} dB make-up gain.")

            latencies: Dict[str, float] = {}

            # Ensure engines are loaded (waits on lock if pre-warming is underway)
            try:
                if not self.clear_engine.is_loaded:
                    self.clear_engine.load()
                if not self.voz_engine.is_loaded:
                    self.voz_engine.load()
            except Exception as e:
                print(f"[Pipeline Error] Speech engine failed to start: {e}")
                traceback.print_exc()
                self._hud("show_notice", "Speech engine failed to start")
                return

            # Stage 1: Clear
            t0 = time.time()
            clean_audio = self.clear_engine.enhance(raw_audio, sr)
            latencies["clear"] = (time.time() - t0) * 1000

            # Stage 2: Uhm acoustic gate
            t0 = time.time()
            gated_audio = self.uhm_engine.apply_acoustic_gate(clean_audio, sr)
            latencies["uhm_gate"] = (time.time() - t0) * 1000
            if len(gated_audio) < int(sr * MIN_SPEECH_SEC):
                print("[Pipeline] No speech detected in recording.")
                self._hud("show_notice", "Didn't catch that")
                return

            # Stage 3: Voz STT
            t0 = time.time()
            raw_text = self.voz_engine.transcribe(gated_audio, sr)
            latencies["voz"] = (time.time() - t0) * 1000
            print(f"[Pipeline] Recognized: '{raw_text}' (Clear: {latencies['clear']:.1f}ms, Voz: {latencies['voz']:.1f}ms)")

            if not raw_text.strip():
                print("[Pipeline] No speech recognized.")
                self._hud("show_notice", "Didn't catch that")
                return

            # Stage 4: disfluencies & editorial rollback
            clean_text = self.uhm_engine.strip_disfluencies(raw_text)
            if not clean_text.strip():
                self._hud("hide")
                return

            # Stage 5: punctuation & spoken commands
            t0 = time.time()
            formatted_text = self.formatter.format(clean_text)
            latencies["format"] = (time.time() - t0) * 1000

            # Stage 6: context-aware window adaptation
            t0 = time.time()
            category, proc_name = self.window_adapter.get_active_context()
            adapted_text = self.window_adapter.adapt_text(formatted_text)
            latencies["adapter"] = (time.time() - t0) * 1000
            if category != "general":
                print(f"[Context] Active window [{proc_name}] -> Applied '{category}' formatting rules.")

            # Stage 7: privacy shield
            is_redacted = False
            final_text = self.redact_engine.redact(adapted_text)
            if self.redact_engine.enabled and final_text != adapted_text:
                is_redacted = True
                print("[Privacy] Redacted sensitive PII tokens prior to injection.")

            if not final_text.strip():
                self._hud("hide")
                return
            print(f"[Pipeline] Final Output: '{final_text}'")

            # Stage 8: injection
            t0 = time.time()
            self.state_mgr.transition_to(AppState.INJECTING)
            self.injector.inject_text(final_text)
            latencies["injection"] = (time.time() - t0) * 1000
            print("[Pipeline] Injection complete. Returning to IDLE.\n")

            self._hud("show_success")

            # Stage 9: history
            try:
                self.logger.log_entry(
                    raw_text=raw_text,
                    final_text=final_text,
                    duration_sec=duration_sec,
                    app_context={"category": category, "process": proc_name},
                    latencies_ms=latencies,
                    audio_buffer=raw_audio,
                    sample_rate=sr,
                    redacted=is_redacted
                )
            except Exception as e:
                print(f"[Logger Warning] Could not record history entry: {e}")

        except Exception as e:
            print(f"[Pipeline Error] Exception in dictation cycle: {type(e).__name__}: {e}")
            traceback.print_exc()
            self._hud("show_notice", "Something went wrong")
        finally:
            self.state_mgr.transition_to(AppState.IDLE)

    # ----------------------------------------------------------------- lifecycle
    def shutdown(self):
        print("[Pipeline] Shutting down background resources...")
        self._stop_watchdog.set()
        try:
            self.capture.shutdown()
        except Exception as e:
            print(f"[Shutdown Notice] capture: {e}")
        try:
            self.voz_engine.unload()
        except Exception as e:
            print(f"[Shutdown Notice] voz: {e}")
        self._hud("hide")

    def _idle_watchdog(self):
        """Evicts models after inactivity and rescues the state machine if a cycle wedges."""
        while not self._stop_watchdog.wait(5.0):
            try:
                state = self.state_mgr.current
                elapsed = time.time() - self.state_mgr.last_state_change

                if state in (AppState.PROCESSING, AppState.INJECTING) and elapsed > STUCK_STATE_TIMEOUT_SEC:
                    print(f"[Resource Manager] State {state.name} stuck for {elapsed:.0f}s; forcing IDLE.")
                    self.state_mgr.transition_to(AppState.IDLE)
                    self._hud("hide")
                    continue

                if state == AppState.IDLE and not self._is_sleeping and elapsed >= self.ttl_sec:
                    print(f"[Resource Manager] TTL ({self.ttl_sec}s) reached without activity. Evicting models to cold storage...")
                    self._is_sleeping = True
                    self.clear_engine.unload()
                    self.voz_engine.unload()
                    gc.collect()
                    try:
                        ctypes.windll.psapi.EmptyWorkingSet(ctypes.windll.kernel32.GetCurrentProcess())
                    except Exception:
                        pass
                    print("[Resource Manager] Cold storage active. Memory reduced to baseline.")
            except Exception as e:
                print(f"[Resource Manager Error] {type(e).__name__}: {e}")
