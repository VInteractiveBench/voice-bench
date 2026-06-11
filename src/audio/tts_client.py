"""Vietnamese text-to-speech via ElevenLabs, mapped to regional voices.

`accent_region` selects an ElevenLabs voice id from the environment
(`TAU2_VOICE_ID_MIEN_BAC / _MIEN_TRUNG / _MIEN_NAM`); `speech_speed` adjusts the
voice-settings speed. Output is requested directly as 24 kHz PCM16, so no resampling
is needed. The ElevenLabs client is injectable so the unit tests run offline.
"""
from __future__ import annotations

import os
import time

import numpy as np

from . import audio_io

VOICE_ENV = {
    "north": "TAU2_VOICE_ID_MIEN_BAC",
    "central": "TAU2_VOICE_ID_MIEN_TRUNG",
    "south": "TAU2_VOICE_ID_MIEN_NAM",
}

SPEED = {"slow": 0.85, "normal": 1.0, "fast": 1.15}

OUTPUT_FORMAT = "pcm_24000"  # raw little-endian PCM16, 24 kHz mono


class ViviTTS:
    def __init__(self, client=None, model_id: str = "eleven_multilingual_v2", max_retries: int = 3) -> None:
        self._client = client
        self.model_id = model_id
        self.max_retries = max_retries

    def _get_client(self):
        if self._client is None:
            api_key = os.getenv("ELEVENLABS_API_KEY")
            if not api_key:
                raise RuntimeError("ELEVENLABS_API_KEY is required for ElevenLabs TTS")
            from elevenlabs.client import ElevenLabs

            self._client = ElevenLabs(api_key=api_key)
        return self._client

    def voice_id(self, accent_region: str) -> str:
        env_name = VOICE_ENV.get(accent_region)
        if env_name is None:
            raise ValueError(f"Unknown accent_region: {accent_region}")
        voice = os.getenv(env_name)
        if not voice:
            raise RuntimeError(f"Voice id env var {env_name} is not set (see .env)")
        return voice

    def _voice_settings(self, speed: float):
        try:
            from elevenlabs import VoiceSettings

            return VoiceSettings(stability=0.5, similarity_boost=0.75, speed=speed)
        except Exception:
            return {"stability": 0.5, "similarity_boost": 0.75, "speed": speed}

    def synthesize(self, text: str, accent_region: str, speech_speed: str = "normal") -> np.ndarray:
        """Return float32 mono 24 kHz samples for the spoken `text`."""
        voice = self.voice_id(accent_region)
        speed = SPEED.get(speech_speed, 1.0)
        client = self._get_client()

        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                stream = client.text_to_speech.convert(
                    voice_id=voice,
                    text=text,
                    model_id=self.model_id,
                    output_format=OUTPUT_FORMAT,
                    voice_settings=self._voice_settings(speed),
                )
                pcm = stream if isinstance(stream, (bytes, bytearray)) else b"".join(stream)
                if not pcm:
                    raise RuntimeError("ElevenLabs returned empty audio")
                return audio_io.pcm16_to_float(bytes(pcm))
            except Exception as exc:  # noqa: BLE001 - ret(ry then re-raise)
                last_error = exc
                time.sleep(0.5 * (attempt + 1))
        raise RuntimeError(f"ElevenLabs TTS failed after {self.max_retries} attempts: {last_error}")
