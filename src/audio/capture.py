"""
Low-Latency Persistent Audio Capture Engine

- Persistent background InputStream (no PortAudio open/close race on hotkey press).
- Smart device selection: configured device (by name or legacy index) -> system
  default -> every other real microphone. Virtual/loopback endpoints, WDM-KS and
  duplicate host-API entries are filtered out.
- Dead-device recovery: if a recording comes back with essentially zero signal
  (virtual mic with no source, Bluetooth headset not in call profile, muted
  endpoint) the engine rotates to the next candidate microphone.
- Native-rate capture with polyphase resampling to the pipeline rate, multi-channel
  downmix, bounded buffer, and live level/spectrum callbacks for the HUD.
"""

import threading
import time
import weakref
from dataclasses import dataclass
from math import gcd
from typing import Callable, List, Optional, Sequence, Tuple, Union

import numpy as np
import scipy.signal
import sounddevice as sd

# Peak amplitude below which a capture is considered electrically dead
# (a live mic's noise floor is >= ~1e-3; dead/virtual endpoints return 0 or 1e-5 dither).
DEAD_PEAK_THRESHOLD = 5e-4

_HOSTAPI_RANK = {"Windows WASAPI": 0, "MME": 1, "Windows DirectSound": 2}
_EXCLUDED_NAME_TOKENS = (
    "sound mapper", "primary sound capture", "stereo mix", "loopback",
    "what u hear", "steam streaming", "midi", "wave out mix", "output",
)
# MME truncates endpoint names to 31 chars (30 once trailing whitespace is stripped)
_MME_NAME_LIMIT = 30
# Spectrum band edges (Hz) used for the HUD visualizer
_BAND_EDGES_HZ = [80, 150, 250, 400, 600, 900, 1300, 1900, 2800, 4000, 5600, 8000]

DeviceSpec = Optional[Union[int, str]]

# Live capture managers, so a device rescan can close and reopen their streams around the
# PortAudio re-initialisation (Settings may run in the same process as the pipeline).
_managers: "weakref.WeakSet[AudioCaptureManager]" = weakref.WeakSet()


@dataclass
class InputDevice:
    index: int
    name: str
    hostapi: str
    channels: int
    default_samplerate: float
    is_default: bool = False


def _clean_name(name: str) -> str:
    return " ".join(str(name).replace("\r", " ").replace("\n", " ").split())


def _same_device(a: str, b: str) -> bool:
    """Exact match, or prefix match when the shorter name looks MME-truncated."""
    a, b = a.lower().strip(), b.lower().strip()
    if not a or not b:
        return False
    if a == b:
        return True
    short, long_ = (a, b) if len(a) < len(b) else (b, a)
    return len(short) >= _MME_NAME_LIMIT and long_.startswith(short)


def rescan_devices() -> bool:
    """
    Re-initialise PortAudio so newly plugged / enabled microphones become visible
    (PortAudio snapshots the device list at init). Open capture streams are closed first
    and reopened afterwards. Skipped while a dictation is recording; returns False then.
    """
    managers = list(_managers)
    if any(m._recording for m in managers):
        return False
    for m in managers:
        m._stream_lock.acquire()
    try:
        for m in managers:
            m._close_stream()
        try:
            sd._terminate()
            sd._initialize()
        except Exception as e:
            print(f"[Audio Notice] Device rescan: {e}")
            return False
        return True
    finally:
        for m in managers:
            if not m._shut:
                m._ensure_stream()
            m._stream_lock.release()


def list_input_devices() -> List[InputDevice]:
    """Real, user-selectable microphones: one entry per physical endpoint, best host API first."""
    try:
        all_devs = sd.query_devices()
        hostapis = sd.query_hostapis()
    except Exception as e:
        print(f"[Audio Error] Could not enumerate audio devices: {e}")
        return []

    default_name = ""
    try:
        default_name = _clean_name(sd.query_devices(kind="input").get("name", ""))
    except Exception:
        pass

    found: List[InputDevice] = []
    for idx, d in enumerate(all_devs):
        try:
            if d.get("max_input_channels", 0) <= 0:
                continue
            api = hostapis[d["hostapi"]]["name"]
            if api not in _HOSTAPI_RANK:
                continue  # skips WDM-KS (raw kernel streaming returns garbage for many drivers)
            name = _clean_name(d["name"])
            if any(tok in name.lower() for tok in _EXCLUDED_NAME_TOKENS):
                continue
            found.append(InputDevice(
                index=idx, name=name, hostapi=api,
                channels=int(d["max_input_channels"]),
                default_samplerate=float(d.get("default_samplerate", 48000.0)),
            ))
        except Exception:
            continue

    # Deduplicate across host APIs, keeping the best-ranked (and longest-named) entry
    found.sort(key=lambda x: (_HOSTAPI_RANK[x.hostapi], -len(x.name), x.index))
    unique: List[InputDevice] = []
    for dev in found:
        if not any(_same_device(dev.name, u.name) for u in unique):
            unique.append(dev)

    for u in unique:
        u.is_default = _same_device(u.name, default_name)
    unique.sort(key=lambda x: (not x.is_default, x.name.lower()))
    return unique


def _match_spec(devices: Sequence[InputDevice], spec: DeviceSpec) -> Optional[InputDevice]:
    if spec is None or spec == "":
        return None
    if isinstance(spec, int):
        for d in devices:
            if d.index == spec:
                return d
        # Legacy index may point to a duplicate-API entry that was deduped: match by name
        try:
            legacy_name = _clean_name(sd.query_devices(spec)["name"])
            for d in devices:
                if _same_device(d.name, legacy_name):
                    return d
        except Exception:
            pass
        return None
    for d in devices:
        if _same_device(d.name, str(spec)):
            return d
    return None


class AudioCaptureManager:
    def __init__(
        self,
        sample_rate: Optional[int] = None,
        target_sample_rate: int = 48000,
        channels: int = 1,
        device_index: DeviceSpec = None,
        trailing_flush_ms: int = 350,
        level_callback: Optional[Callable[..., None]] = None,
        buffer_duration_sec: float = 120.0,
        **kwargs,
    ):
        self.target_sample_rate = int(sample_rate or target_sample_rate)
        self.channels = max(1, int(channels))
        self.device_spec: DeviceSpec = device_index
        self.trailing_flush_ms = trailing_flush_ms
        self.level_callback = level_callback
        self.max_frames_sec = float(buffer_duration_sec)

        self._recording = False
        self._audio_frames: List[np.ndarray] = []
        self._frame_count = 0
        self._lock = threading.Lock()
        self._stream_lock = threading.RLock()

        self._stream: Optional[sd.InputStream] = None
        self._native_sample_rate = self.target_sample_rate
        self._stream_channels = 1
        self._resample_up = 1
        self._resample_down = 1

        self.device_name = "Default Microphone"
        self._dead_devices: List[str] = []
        self._rec_peak = 0.0
        self._cap_warned = False
        self.last_peak = 0.0
        self.last_rms = 0.0
        self._shut = False

        _managers.add(self)
        self._ensure_stream()

    # ------------------------------------------------------------------ devices
    def set_device(self, spec: DeviceSpec):
        """Switch microphone at runtime (called when Settings change)."""
        if spec == self.device_spec and self._stream is not None and getattr(self._stream, "active", False):
            return
        self.device_spec = spec
        self._dead_devices = []
        self.refresh_devices()  # the chosen mic may have been plugged in after launch
        self._ensure_stream()

    def _candidates(self) -> List[InputDevice]:
        devices = list_input_devices()
        ordered: List[InputDevice] = []

        preferred = _match_spec(devices, self.device_spec)
        if preferred:
            ordered.append(preferred)
        elif self.device_spec not in (None, ""):
            print(f"[Audio Notice] Configured microphone '{self.device_spec}' not found; using system default.")

        for d in devices:  # default first (list is sorted default-first)
            if d not in ordered:
                ordered.append(d)

        alive = [d for d in ordered if d.name not in self._dead_devices]
        return alive or ordered

    def _open(self, dev: InputDevice) -> Optional[sd.InputStream]:
        """Open a device trying native rate/channel combos; returns a started stream or None."""
        rates = [dev.default_samplerate]
        if 48000.0 not in rates:
            rates.append(48000.0)
        chans = [1] if dev.channels < 2 else [1, 2]

        extra = None
        if dev.hostapi == "Windows WASAPI":
            try:
                extra = sd.WasapiSettings(auto_convert=True)
            except Exception:
                extra = None

        last_err: Optional[Exception] = None
        for sr in rates:
            for ch in chans:
                for ex in ([extra, None] if extra is not None else [None]):
                    try:
                        stream = sd.InputStream(
                            device=dev.index, samplerate=sr, channels=ch, dtype="float32",
                            blocksize=int(sr * 0.02), callback=self._audio_callback,
                            extra_settings=ex,
                        )
                        stream.start()
                        self._native_sample_rate = int(sr)
                        self._stream_channels = ch
                        return stream
                    except Exception as e:
                        last_err = e
        print(f"[Audio Error] Could not open '{dev.name}' ({dev.hostapi}): {last_err}")
        return None

    def _set_resampler(self):
        if self._native_sample_rate != self.target_sample_rate:
            g = gcd(self.target_sample_rate, self._native_sample_rate)
            self._resample_up = self.target_sample_rate // g
            self._resample_down = self._native_sample_rate // g
        else:
            self._resample_up = self._resample_down = 1

    def _close_stream(self):
        with self._stream_lock:
            if self._stream is not None:
                try:
                    self._stream.abort()
                    self._stream.close()
                except Exception as e:
                    print(f"[Audio Notice] Stream close: {e}")
                self._stream = None

    def _ensure_stream(self) -> bool:
        """Ensures a live stream exists; opens the best available microphone if not."""
        with self._stream_lock:
            if self._stream is not None and getattr(self._stream, "active", False):
                return True
            self._close_stream()

            for dev in self._candidates():
                stream = self._open(dev)
                if stream is not None:
                    self._stream = stream
                    self.device_name = dev.name
                    self._set_resampler()
                    print(f"[Audio Engine] Persistent stream online on '{dev.name}' "
                          f"({dev.hostapi}, {self._native_sample_rate}Hz, {self._stream_channels}ch).")
                    return True

            print("[Audio Fatal] No usable audio input device could be opened.")
            return False

    def refresh_devices(self):
        """Re-scan PortAudio's device list (picks up newly plugged/changed default devices)."""
        rescan_devices()

    def handle_dead_signal(self) -> Optional[str]:
        """
        Called when a recording had no usable signal. Marks the device dead and rotates to the
        next candidate. Returns the new device's name, or None if no alternative was available.
        """
        with self._stream_lock:
            failed = self.device_name
            if failed and failed not in self._dead_devices:
                self._dead_devices.append(failed)
            print(f"[Audio Notice] No signal from '{failed}'. Searching for a working microphone...")
            self.refresh_devices()
            devices = list_input_devices()
            remaining = [d for d in devices if d.name not in self._dead_devices]
            if not remaining:
                self._dead_devices = []  # cycled through everything; start over next time
                self._ensure_stream()
                return None
            self._ensure_stream()
            return self.device_name if self.device_name not in self._dead_devices else None

    # ---------------------------------------------------------------- streaming
    def _audio_callback(self, indata, frames, time_info, status):
        """PortAudio thread: must never raise and must stay cheap."""
        if not self._recording:
            return
        try:
            if indata.ndim > 1 and indata.shape[1] > 1:
                mono = indata.mean(axis=1)
            else:
                mono = indata.reshape(-1)
            chunk = mono.astype(np.float32, copy=True)

            peak = float(np.max(np.abs(chunk))) if chunk.size else 0.0
            if peak > self._rec_peak:
                self._rec_peak = peak

            with self._lock:
                if self._recording:
                    max_samples = int(self.max_frames_sec * self._native_sample_rate)
                    if self._frame_count < max_samples:
                        self._audio_frames.append(chunk)
                        self._frame_count += chunk.size
                    elif not self._cap_warned:
                        self._cap_warned = True
                        print(f"[Audio Notice] Recording buffer cap ({self.max_frames_sec:.0f}s) reached.")

            cb = self.level_callback
            if cb is not None and chunk.size:
                rms = float(np.sqrt(np.mean(chunk * chunk)))
                try:
                    cb(rms, self._spectrum_bands(chunk))
                except Exception:
                    cb(rms, [])
        except Exception:
            pass

    def _spectrum_bands(self, chunk: np.ndarray) -> List[float]:
        """11-band vocal spectrum energy (80Hz-8kHz) for the HUD visualizer."""
        n = chunk.size
        if n < 64:
            return []
        windowed = chunk * np.hanning(n).astype(np.float32)
        mag = np.abs(np.fft.rfft(windowed))
        nyq = self._native_sample_rate / 2.0
        n_bins = mag.size
        bands = []
        for lo, hi in zip(_BAND_EDGES_HZ[:-1], _BAND_EDGES_HZ[1:]):
            i1 = min(n_bins - 1, int(lo / nyq * n_bins))
            i2 = min(n_bins, max(i1 + 1, int(hi / nyq * n_bins)))
            bands.append(float(np.mean(mag[i1:i2])))
        return bands

    # ---------------------------------------------------------------- recording
    def start_recording(self):
        """Begins capturing immediately (stream is already running)."""
        with self._lock:
            self._audio_frames = []
            self._frame_count = 0
            self._rec_peak = 0.0
            self._cap_warned = False
            self._recording = True
        self._ensure_stream()

    def _finalize(self, frames: List[np.ndarray]) -> np.ndarray:
        if not frames:
            return np.zeros(0, dtype=np.float32)
        audio = np.concatenate(frames).astype(np.float32, copy=False)
        if self._resample_up != self._resample_down:
            audio = scipy.signal.resample_poly(audio, self._resample_up, self._resample_down).astype(np.float32)
        return audio

    def get_buffered_audio(self) -> np.ndarray:
        with self._lock:
            frames = list(self._audio_frames)
        return self._finalize(frames)

    def stop_recording(self) -> np.ndarray:
        """Stops capture (after a short tail flush) and returns float32 mono audio at target rate."""
        time.sleep(self.trailing_flush_ms / 1000.0)
        with self._lock:
            self._recording = False
            frames = self._audio_frames
            self._audio_frames = []
            self._frame_count = 0

        audio = self._finalize(frames)
        if audio.size:
            self.last_peak = float(np.max(np.abs(audio)))
            self.last_rms = float(np.sqrt(np.mean(audio * audio)))
        else:
            self.last_peak = self.last_rms = 0.0
        return audio

    def shutdown(self):
        self._shut = True
        self._recording = False
        self._close_stream()
        _managers.discard(self)
