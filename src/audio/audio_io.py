"""Low-level audio helpers: load, save, resample, downmix, PCM16 conversion.

Everything in the pipeline works on float32 mono samples in [-1, 1] at a single
canonical rate. PCM16 byte strings are produced only at the boundaries (TTS output
decoding and Realtime streaming).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

# OpenAI Realtime GA expects 24 kHz PCM16 mono input.
TARGET_SR = 24000


def to_mono(samples: np.ndarray) -> np.ndarray:
    """Average channels to mono. Accepts (n,), (n, channels) or (channels, n)."""
    array = np.asarray(samples, dtype=np.float32)
    if array.ndim == 1:
        return array
    # soundfile returns (frames, channels); collapse the channel axis.
    if array.shape[0] < array.shape[1] and array.shape[0] <= 8:
        # (channels, n) layout
        return array.mean(axis=0).astype(np.float32)
    return array.mean(axis=1).astype(np.float32)


def resample(samples: np.ndarray, sr_in: int, sr_out: int = TARGET_SR) -> np.ndarray:
    """Resample mono float samples from sr_in to sr_out."""
    array = np.asarray(samples, dtype=np.float32)
    if sr_in == sr_out:
        return array
    import librosa

    return librosa.resample(array, orig_sr=sr_in, target_sr=sr_out).astype(np.float32)


def load_audio(path: str | Path, target_sr: int = TARGET_SR) -> np.ndarray:
    """Load any WAV as float32 mono at target_sr."""
    import soundfile as sf

    data, sr = sf.read(str(path), dtype="float32", always_2d=False)
    mono = to_mono(data)
    return resample(mono, sr, target_sr)


def save_wav(path: str | Path, samples: np.ndarray, sr: int = TARGET_SR) -> None:
    """Write float32 mono samples to a PCM16 WAV."""
    import soundfile as sf

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    array = np.clip(np.asarray(samples, dtype=np.float32), -1.0, 1.0)
    sf.write(str(target), array, sr, subtype="PCM_16")


def float_to_pcm16(samples: np.ndarray) -> bytes:
    """Convert float32 samples in [-1, 1] to little-endian PCM16 bytes."""
    array = np.clip(np.asarray(samples, dtype=np.float32), -1.0, 1.0)
    return (array * 32767.0).astype("<i2").tobytes()


def pcm16_to_float(data: bytes) -> np.ndarray:
    """Convert little-endian PCM16 bytes to float32 samples in [-1, 1]."""
    return np.frombuffer(data, dtype="<i2").astype(np.float32) / 32768.0
