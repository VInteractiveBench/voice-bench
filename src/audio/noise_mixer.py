"""Mix Vietnamese speech with cabin/road/street noise at a target SNR.

Layer sources (under data/voice/, semantics confirmed by the project owner):
  - cabin-sound/segments/  in-cabin mixed noise bed (people/radio/engine), pre-segmented
  - engine-sound/          car-running / engine clips (road layer)
  - continuous/            outdoor street ambience (interaction_stress only)
  - bursts/                sudden external one-shots (interaction_stress only)

A condition's SNR is drawn from its yaml `snr_db_range`, seeded per episode so runs
are reproducible. `clean` returns the speech untouched.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import audio_io

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA_ROOT = REPO_ROOT / "data" / "voice"
DEFAULT_CONDITIONS_DIR = REPO_ROOT / "src" / "audio_conditions"


@dataclass(frozen=True)
class Layer:
    kind: str  # "bed" (continuous, looped) or "oneshot" (sparse bursts)
    folder: str  # relative to data_root
    gain: float


# Relative folder + gain per condition. Gains are pre-SNR; the combined bed is then
# rescaled to hit the requested SNR, so these only set the balance between layers.
CONDITION_LAYERS: dict[str, list[Layer]] = {
    "clean": [],
    "cabin_noise": [
        Layer("bed", "cabin-sound/segments", 1.0),
        Layer("bed", "engine-sound", 0.5),
    ],
    "interaction_stress": [
        Layer("bed", "cabin-sound/segments", 1.0),
        Layer("bed", "engine-sound", 0.5),
        Layer("bed", "continuous", 0.4),
        Layer("oneshot", "bursts", 0.7),
    ],
}


def _load_condition(conditions_dir: Path, condition_id: str) -> dict:
    import yaml

    path = conditions_dir / f"{condition_id}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Unknown audio condition: {path}")
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _rms(samples: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(samples)))) if len(samples) else 0.0


class NoiseMixer:
    def __init__(
        self,
        data_root: Path | str = DEFAULT_DATA_ROOT,
        conditions_dir: Path | str = DEFAULT_CONDITIONS_DIR,
    ) -> None:
        self.data_root = Path(data_root)
        self.conditions_dir = Path(conditions_dir)

    def _files(self, folder: str) -> list[Path]:
        return sorted((self.data_root / folder).glob("*.wav"))

    def _continuous_bed(self, folder: str, length: int, rng: np.random.Generator) -> np.ndarray:
        files = self._files(folder)
        if not files:
            raise FileNotFoundError(
                f"Noise layer '{folder}' is empty under {self.data_root}. "
                f"For cabin-sound/segments run scripts/segment_cabin_noise.py first."
            )
        bed = np.zeros(length, dtype=np.float32)
        filled = 0
        # Concatenate random clips until the bed is covered.
        while filled < length:
            clip = audio_io.load_audio(files[rng.integers(len(files))], audio_io.TARGET_SR)
            if len(clip) == 0:
                continue
            take = min(len(clip), length - filled)
            start = int(rng.integers(0, max(1, len(clip) - take + 1)))
            bed[filled:filled + take] = clip[start:start + take]
            filled += take
        return bed

    def _oneshot_bed(self, folder: str, length: int, rng: np.random.Generator) -> np.ndarray:
        files = self._files(folder)
        if not files:
            raise FileNotFoundError(f"Noise layer '{folder}' is empty under {self.data_root}.")
        bed = np.zeros(length, dtype=np.float32)
        n_bursts = max(1, length // audio_io.TARGET_SR // 3)  # ~1 burst per 3 s
        for _ in range(n_bursts):
            clip = audio_io.load_audio(files[rng.integers(len(files))], audio_io.TARGET_SR)
            if len(clip) == 0 or len(clip) >= length:
                continue
            start = int(rng.integers(0, length - len(clip)))
            bed[start:start + len(clip)] += clip
        return bed

    def mix(self, speech: np.ndarray, condition_id: str, seed: int) -> np.ndarray:
        speech = np.asarray(speech, dtype=np.float32)
        config = _load_condition(self.conditions_dir, condition_id)
        layers = CONDITION_LAYERS.get(condition_id, [])
        snr_range = config.get("snr_db_range")
        if not layers or not snr_range:
            return speech  # clean

        rng = np.random.default_rng(seed)
        length = len(speech)
        bed = np.zeros(length, dtype=np.float32)
        for layer in layers:
            if layer.kind == "bed":
                bed += layer.gain * self._continuous_bed(layer.folder, length, rng)
            else:
                bed += layer.gain * self._oneshot_bed(layer.folder, length, rng)

        speech_rms = _rms(speech)
        bed_rms = _rms(bed)
        if speech_rms == 0.0 or bed_rms == 0.0:
            return speech
        snr_db = float(rng.uniform(snr_range[0], snr_range[1]))
        target_bed_rms = speech_rms / (10 ** (snr_db / 20))
        bed *= target_bed_rms / bed_rms
        return np.clip(speech + bed, -1.0, 1.0).astype(np.float32)
