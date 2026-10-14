"""
Dictation History Logger for Takt.
Logs every voice recording, transcription, active application context, 
and pipeline latency metrics to persistent storage.
Maintains a rolling ring-buffer of the last N raw voice audio recordings (.wav).
"""

import os
import json
import time
from datetime import datetime
from typing import Dict, Any, Optional
import numpy as np
import soundfile as sf

class DictationLogger:
    def __init__(
        self,
        log_dir: str = "logs",
        enabled: bool = True,
        save_audio: bool = True,
        max_audio_recordings: int = 10
    ):
        self.log_dir = log_dir
        self.enabled = enabled
        self.save_audio = save_audio
        self.max_audio_recordings = max_audio_recordings
        self.recordings_dir = os.path.join(self.log_dir, "recordings")

        if self.enabled:
            os.makedirs(self.log_dir, exist_ok=True)
            if self.save_audio:
                os.makedirs(self.recordings_dir, exist_ok=True)

        self.text_log_file = os.path.join(self.log_dir, "dictation_history.log")
        self.json_log_file = os.path.join(self.log_dir, "dictation_history.jsonl")

    def log_entry(
        self,
        raw_text: str,
        final_text: str,
        duration_sec: float,
        app_context: Dict[str, str],
        latencies_ms: Dict[str, float],
        audio_buffer: Optional[np.ndarray] = None,
        sample_rate: int = 48000,
        redacted: bool = False
    ):
        """Records a completed dictation event to disk."""
        if not self.enabled:
            return

        now = datetime.now()
        timestamp_str = now.strftime("%Y-%m-%d %H:%M:%S")
        file_ts = now.strftime("%Y%m%d_%H%M%S_%f")[:19]

        audio_rel_path = None
        if self.save_audio and audio_buffer is not None and len(audio_buffer) > 0:
            audio_rel_path = self.save_recording(audio_buffer, sample_rate, file_ts)

        proc = app_context.get("process", "unknown")
        total_lat = sum(latencies_ms.values()) if latencies_ms else 0.0

        # 1. Human-Readable Log
        audio_info = f" | Audio: {audio_rel_path}" if audio_rel_path else ""
        text_line = (
            f"[{timestamp_str}] [{proc}] ({duration_sec:.1f}s audio, {total_lat:.0f}ms latency{audio_info})\n"
            f"  Text: {final_text}\n"
        )
        if raw_text != final_text:
            text_line += f"  (Raw: {raw_text})\n"
        text_line += "\n"

        try:
            with open(self.text_log_file, "a", encoding="utf-8") as f:
                f.write(text_line)
        except Exception as e:
            print(f"[Logger Warning] Failed to append to text log: {e}")

        # 2. Structured JSONL Log
        record = {
            "timestamp": timestamp_str,
            "duration_sec": round(duration_sec, 3),
            "total_latency_ms": round(total_lat, 1),
            "latencies_ms": {k: round(v, 1) for k, v in latencies_ms.items()},
            "app_context": app_context,
            "raw_text": raw_text,
            "final_text": final_text,
            "audio_file": audio_rel_path,
            "redacted": redacted
        }
        try:
            with open(self.json_log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(record) + "\n")
        except Exception as e:
            print(f"[Logger Warning] Failed to append to jsonl log: {e}")

    def save_recording(self, audio_buffer: np.ndarray, sample_rate: int, file_ts: str) -> str:
        """Saves audio buffer to a WAV file in recordings_dir and enforces max limit."""
        try:
            filename = f"recording_{file_ts}.wav"
            full_path = os.path.join(self.recordings_dir, filename)
            sf.write(full_path, audio_buffer, sample_rate, subtype="PCM_16")

            # Rotate recordings to keep only max_audio_recordings
            self._rotate_recordings()

            # Return relative path for logging
            return os.path.relpath(full_path, self.log_dir)
        except Exception as e:
            print(f"[Logger Warning] Failed to save WAV recording: {e}")
            return ""

    def _rotate_recordings(self):
        """Deletes oldest audio recordings if count exceeds max_audio_recordings."""
        try:
            if not os.path.exists(self.recordings_dir):
                return

            wav_files = [
                os.path.join(self.recordings_dir, f)
                for f in os.listdir(self.recordings_dir)
                if f.lower().endswith(".wav")
            ]
            if len(wav_files) > self.max_audio_recordings:
                # Sort by modification time ascending (oldest first)
                wav_files.sort(key=os.path.getmtime)
                excess = len(wav_files) - self.max_audio_recordings
                for i in range(excess):
                    try:
                        os.remove(wav_files[i])
                    except Exception:
                        pass
        except Exception as e:
            print(f"[Logger Warning] Error rotating audio files: {e}")
