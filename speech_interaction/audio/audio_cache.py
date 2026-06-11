"""Disk-cached spoken-audio builder.

`get_or_build` returns 24 kHz mono float samples for a given utterance/persona/condition,
synthesizing (TTS) + mixing only on a cache miss. The noise seed is derived from the cache
key, so the same inputs always yield the same audio — reproducible and cache-consistent.
This makes re-runs and the full sweep nearly free after the first pass.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np

from . import audio_io
from .noise_mixer import DEFAULT_CONDITIONS_DIR, NoiseMixer
from .tts_client import ViviTTS

DEFAULT_CACHE_DIR = Path(__file__).resolve().parents[2] / "data" / "voice" / "_cache"


class AudioCache:
    def __init__(
        self,
        tts: ViviTTS | None = None,
        mixer: NoiseMixer | None = None,
        cache_dir: Path | str = DEFAULT_CACHE_DIR,
    ) -> None:
        self.tts = tts or ViviTTS()
        self.mixer = mixer or NoiseMixer(conditions_dir=DEFAULT_CONDITIONS_DIR)
        self.cache_dir = Path(cache_dir)

    @staticmethod
    def _key(text: str, accent_region: str, speech_speed: str, condition_id: str) -> str:
        raw = f"{text}|{accent_region}|{speech_speed}|{condition_id}".encode("utf-8")
        return hashlib.sha1(raw).hexdigest()

    def get_or_build(
        self, text: str, accent_region: str, speech_speed: str, condition_id: str
    ) -> np.ndarray:
        key = self._key(text, accent_region, speech_speed, condition_id)
        path = self.cache_dir / f"{key}.wav"
        if path.exists():
            return audio_io.load_audio(path, audio_io.TARGET_SR)
        speech = self.tts.synthesize(text, accent_region, speech_speed)
        seed = int(key[:8], 16)
        mixed = self.mixer.mix(speech, condition_id, seed)
        audio_io.save_wav(path, mixed, audio_io.TARGET_SR)
        return mixed
