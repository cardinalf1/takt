"""
Desert Ant Labs 'Uhm' & Acoustic Disfluency Gate
Eliminates verbal fillers ("um", "uh", "er", "you know", "kinda like"),
repetitive stutters, and low-energy speech pauses prior to transcription and formatting.
Loads categorized disfluency taxonomies from config/disfluencies.yaml.
"""

import os
import sys
import re
import yaml
import numpy as np
from typing import Tuple, List, Optional

class DALUhmEngine:
    def __init__(
        self, 
        silence_threshold: float = 0.003, 
        min_silence_duration_ms: int = 150,
        trailing_pad_ms: int = 400,
        taxonomy_path: Optional[str] = None
    ):
        self.silence_threshold = silence_threshold
        self.min_silence_duration_ms = min_silence_duration_ms
        self.trailing_pad_ms = trailing_pad_ms
        
        # Load external taxonomy if available
        if taxonomy_path is None:
            if getattr(sys, 'frozen', False):
                base_dir = getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
            else:
                base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
            taxonomy_path = os.path.join(base_dir, "config", "disfluencies.yaml")

        self.taxonomy = {}
        if os.path.exists(taxonomy_path):
            try:
                with open(taxonomy_path, "r", encoding="utf-8") as f:
                    self.taxonomy = yaml.safe_load(f) or {}
            except Exception as e:
                print(f"[DAL Uhm Warning] Could not load {taxonomy_path}: {e}")

        # Fillers: only purely non-lexical acoustic vocalizations (um, uh, er, hmm) are stripped.
        # Words that are legitimate vocabulary in normal speech ("like", "actually", "basically",
        # "kind of", "sort of", "kinda", "sorta", "kinda like", "you know", "i mean") are deliberately
        # NOT stripped: removing them blindly via regex corrupts valid sentences such as
        # "I kinda like how this is coming along" -> "I how this is coming along",
        # "I like it" -> "I it", or "Do you know?" -> "Do?". Contextual cleanup belongs in LLM smart formatters.
        filled_pauses = self.taxonomy.get("filled_pauses", ["uh", "um", "umm", "uhh", "er", "erm", "hmm", "mhm"])
        all_fillers = [w for w in filled_pauses if w]
        # Longest first so multi-word phrases match before their parts
        all_fillers.sort(key=len, reverse=True)
        escaped_fillers = [re.escape(w) for w in all_fillers]

        self.filler_pattern = re.compile(
            r"\b(?:" + "|".join(escaped_fillers) + r")\b,?",
            re.IGNORECASE
        )

        rollbacks = [r for r in self.taxonomy.get("editorial_rollbacks", [])
                     if r.lower() in ("scratch that", "scratch this", "delete that", "erase that", "never mind that")]
        rollbacks += ["scratch that", "delete that", "cross that out"]
        rollbacks = sorted(set(r.lower() for r in rollbacks), key=len, reverse=True)
        self.rollback_pattern = re.compile(
            r"\b(?:" + "|".join(re.escape(r) for r in rollbacks) + r")\b[.,!?]*", re.IGNORECASE)

        word_rb = self.taxonomy.get("word_rollbacks", ["scratch last word", "delete last word", "erase last word"])
        self.word_rollback_pattern = re.compile(
            r"\b(?:" + "|".join(re.escape(r) for r in sorted(word_rb, key=len, reverse=True)) + r")\b[.,!?]*",
            re.IGNORECASE)

        # Stutter / duplicate consecutive words regex (e.g., "I I think" -> "I think")
        self.duplicate_pattern = re.compile(r"\b(\w+)\s+\1\b", re.IGNORECASE)

    def apply_acoustic_gate(self, audio: np.ndarray, sample_rate: int = 48000) -> np.ndarray:
        """
        Trims leading/trailing non-speech and keeps padding around valid speech.
        Threshold adapts to the capture level: max(configured floor, 2.5x the quiet-frame noise
        floor), but never above 35% of the loudest frame so a very short utterance is never dropped.
        Returns an empty array when the buffer holds no speech.
        """
        if len(audio) == 0:
            return audio

        frame_len = int(sample_rate * 0.03)  # 30ms frames
        num_frames = len(audio) // frame_len
        if num_frames < 1:
            return audio

        frames = audio[: num_frames * frame_len].reshape(num_frames, frame_len)
        energies = np.sqrt(np.mean(frames * frames, axis=1))

        loudest = float(np.max(energies))
        noise_floor = float(np.percentile(energies, 15))
        threshold = max(self.silence_threshold, noise_floor * 2.5)
        threshold = min(threshold, loudest * 0.35)
        threshold = max(threshold, self.silence_threshold * 0.5)

        speech_indices = np.where(energies > threshold)[0]
        if len(speech_indices) == 0:
            return np.array([], dtype=audio.dtype)

        start_frame = max(0, speech_indices[0] - 2)
        end_frame = min(num_frames, speech_indices[-1] + 2)

        start_sample = start_frame * frame_len
        end_sample = min(len(audio), end_frame * frame_len + int(sample_rate * (self.trailing_pad_ms / 1000.0)))

        return audio[start_sample:end_sample]

    def strip_disfluencies(self, text: str) -> str:
        """
        Removes verbal fillers, false starts, and repeated stuttered tokens.
        """
        if not text:
            return text

        # 1. Voice Editorial Rollback: "scratch that" discards everything said before it
        parts = self.rollback_pattern.split(text)
        if len(parts) > 1:
            text = parts[-1].strip()
        # "scratch last word" removes the single word immediately before the command
        while True:
            m = self.word_rollback_pattern.search(text)
            if not m:
                break
            before = re.sub(r"\s*\S+\s*$", "", text[:m.start()])
            text = (before + " " + text[m.end():]).strip()

        # 2. Strip fillers & verbal crutches
        cleaned = self.filler_pattern.sub("", text)

        # 3. Strip duplicate stutters ("the the", "I I")
        cleaned = self.duplicate_pattern.sub(r"\1", cleaned)

        # 4. Clean up stray double spaces and orphaned commas
        cleaned = re.sub(r"\s+", " ", cleaned)
        cleaned = re.sub(r"\s+([,;.!?])", r"\1", cleaned)
        cleaned = re.sub(r",\s*,+", ",", cleaned)

        return cleaned.strip()
