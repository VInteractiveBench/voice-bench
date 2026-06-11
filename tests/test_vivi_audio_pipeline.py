"""Offline unit tests for the Vivi real-audio pipeline.

Run with: pytest --noconftest tests/test_vivi_audio_pipeline.py
(the inherited tests/conftest.py imports tau2, which is not installed here).
"""
from __future__ import annotations

import numpy as np

from speech_interaction.audio import audio_io
from speech_interaction.audio.noise_mixer import NoiseMixer
from speech_interaction.audio.tts_client import ViviTTS
from speech_interaction.audio.audio_cache import AudioCache


def _tone(freq: float, seconds: float, sr: int) -> np.ndarray:
    t = np.linspace(0, seconds, int(seconds * sr), endpoint=False)
    return (0.5 * np.sin(2 * np.pi * freq * t)).astype(np.float32)


# ---- audio_io ----

def test_pcm16_roundtrip_preserves_signal():
    samples = _tone(440, 0.05, audio_io.TARGET_SR)
    restored = audio_io.pcm16_to_float(audio_io.float_to_pcm16(samples))
    assert restored.shape == samples.shape
    assert np.max(np.abs(restored - samples)) < 1e-3


def test_float_to_pcm16_clips_out_of_range():
    loud = np.array([2.0, -2.0, 0.0], dtype=np.float32)
    restored = audio_io.pcm16_to_float(audio_io.float_to_pcm16(loud))
    assert restored[0] <= 1.0 and restored[1] >= -1.0


def test_to_mono_averages_stereo():
    stereo = np.stack([np.ones(100), -np.ones(100)], axis=1).astype(np.float32)
    mono = audio_io.to_mono(stereo)
    assert mono.shape == (100,)
    assert np.allclose(mono, 0.0)


def test_resample_changes_length_proportionally():
    samples = _tone(200, 0.1, 16000)
    out = audio_io.resample(samples, 16000, 24000)
    assert abs(len(out) - int(len(samples) * 24000 / 16000)) <= 2


def test_resample_noop_when_rates_match():
    samples = _tone(200, 0.05, 24000)
    out = audio_io.resample(samples, 24000, 24000)
    assert np.array_equal(out, samples)


def test_save_then_load_roundtrip(tmp_path):
    samples = _tone(330, 0.1, audio_io.TARGET_SR)
    path = tmp_path / "tone.wav"
    audio_io.save_wav(path, samples, audio_io.TARGET_SR)
    loaded = audio_io.load_audio(path, audio_io.TARGET_SR)
    assert loaded.ndim == 1
    assert abs(len(loaded) - len(samples)) <= 2


# ---- segment_cabin_noise ----

def test_segment_file_produces_mono_24k_segments(tmp_path):
    import importlib.util
    import soundfile as sf

    root = __import__("pathlib").Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location(
        "segment_cabin_noise", root / "scripts" / "segment_cabin_noise.py"
    )
    seg = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(seg)

    # 2 s of stereo noise at 8 kHz -> 0.5 s segments -> 4 segments.
    native_sr = 8000
    stereo = (np.random.default_rng(0).standard_normal((2 * native_sr, 2)) * 0.1).astype(np.float32)
    src = tmp_path / "fake_cabin.wav"
    sf.write(str(src), stereo, native_sr, subtype="PCM_16")

    out = seg.segment_file(src, tmp_path / "segments", segment_seconds=0.5, target_sr=24000)
    assert len(out) == 4
    info = sf.info(str(out[0]))
    assert info.channels == 1
    assert info.samplerate == 24000
    assert abs(info.duration - 0.5) < 0.05


# ---- noise_mixer ----

def _make_noise_data_root(tmp_path, *, with_car_run=True):
    sr = audio_io.TARGET_SR
    rng = np.random.default_rng(1)
    seg_dir = tmp_path / "cabin-sound" / "segments"
    for i in range(3):
        audio_io.save_wav(seg_dir / f"seg_{i}.wav", (rng.standard_normal(sr) * 0.2).astype(np.float32), sr)
    if with_car_run:
        car_dir = tmp_path / "car-run"
        for i in range(3):
            audio_io.save_wav(car_dir / f"car_{i}.wav", (rng.standard_normal(sr // 2) * 0.2).astype(np.float32), sr)
    return tmp_path


def _make_conditions_dir(tmp_path, snr_low, snr_high):
    cdir = tmp_path / "conds"
    cdir.mkdir(parents=True, exist_ok=True)
    (cdir / "cabin_noise.yaml").write_text(
        f"condition_id: cabin_noise\nnoise_sources:\n- road_noise\nsnr_db_range:\n- {snr_low}\n- {snr_high}\n",
        encoding="utf-8",
    )
    (cdir / "clean.yaml").write_text(
        "condition_id: clean\nnoise_sources: []\nsnr_db_range: null\n", encoding="utf-8"
    )
    return cdir


def test_mix_hits_requested_snr_and_keeps_length(tmp_path):
    data_root = _make_noise_data_root(tmp_path / "data")
    conds = _make_conditions_dir(tmp_path / "c", 15, 15)
    mixer = NoiseMixer(data_root=data_root, conditions_dir=conds)
    speech = _tone(300, 1.0, audio_io.TARGET_SR)

    mixed = mixer.mix(speech, "cabin_noise", seed=7)
    assert len(mixed) == len(speech)
    noise = mixed - speech
    measured_snr = 20 * np.log10(
        np.sqrt(np.mean(speech ** 2)) / np.sqrt(np.mean(noise ** 2))
    )
    assert abs(measured_snr - 15) < 1.5


def test_mix_clean_returns_speech_unchanged(tmp_path):
    data_root = _make_noise_data_root(tmp_path / "data")
    conds = _make_conditions_dir(tmp_path / "c", 15, 15)
    mixer = NoiseMixer(data_root=data_root, conditions_dir=conds)
    speech = _tone(300, 0.3, audio_io.TARGET_SR)
    assert np.array_equal(mixer.mix(speech, "clean", seed=1), speech)


def test_mix_missing_layer_raises(tmp_path):
    data_root = _make_noise_data_root(tmp_path / "data", with_car_run=False)
    conds = _make_conditions_dir(tmp_path / "c", 15, 15)
    mixer = NoiseMixer(data_root=data_root, conditions_dir=conds)
    speech = _tone(300, 0.3, audio_io.TARGET_SR)
    import pytest

    with pytest.raises(FileNotFoundError):
        mixer.mix(speech, "cabin_noise", seed=1)


# ---- tts_client ----

class _FakeConvert:
    def __init__(self, pcm: bytes, calls: list):
        self._pcm = pcm
        self._calls = calls

    def convert(self, **kwargs):
        self._calls.append(kwargs)
        # Yield in two chunks to exercise the join path.
        half = len(self._pcm) // 2
        return iter([self._pcm[:half], self._pcm[half:]])


class _FakeElevenLabs:
    def __init__(self, pcm: bytes):
        self.calls: list = []
        self.text_to_speech = _FakeConvert(pcm, self.calls)


def test_synthesize_decodes_pcm_and_uses_region_voice(monkeypatch):
    monkeypatch.setenv("TAU2_VOICE_ID_MIEN_NAM", "voice_south_123")
    pcm = audio_io.float_to_pcm16(_tone(220, 0.1, audio_io.TARGET_SR))
    fake = _FakeElevenLabs(pcm)
    tts = ViviTTS(client=fake)

    out = tts.synthesize("Xin chào", "south", "fast")
    assert out.dtype == np.float32
    assert len(out) == len(pcm) // 2
    assert fake.calls[0]["voice_id"] == "voice_south_123"
    assert fake.calls[0]["output_format"] == "pcm_24000"


def test_synthesize_missing_voice_env_raises(monkeypatch):
    monkeypatch.delenv("TAU2_VOICE_ID_MIEN_BAC", raising=False)
    tts = ViviTTS(client=_FakeElevenLabs(b"\x00\x00"))
    import pytest

    with pytest.raises(RuntimeError):
        tts.synthesize("test", "north", "normal")


# ---- audio_cache ----

class _CountingTTS:
    def __init__(self, samples):
        self.samples = samples
        self.calls = 0

    def synthesize(self, text, accent_region, speech_speed="normal"):
        self.calls += 1
        return self.samples


def test_cache_miss_builds_then_hit_reads_without_tts(tmp_path):
    conds = _make_conditions_dir(tmp_path / "c", 15, 15)
    mixer = NoiseMixer(data_root=tmp_path / "data", conditions_dir=conds)
    speech = _tone(280, 0.2, audio_io.TARGET_SR)
    tts = _CountingTTS(speech)
    cache = AudioCache(tts=tts, mixer=mixer, cache_dir=tmp_path / "cache")

    first = cache.get_or_build("Mở nhạc", "south", "normal", "clean")
    assert tts.calls == 1
    assert (tmp_path / "cache").glob("*.wav")

    second = cache.get_or_build("Mở nhạc", "south", "normal", "clean")
    assert tts.calls == 1  # served from disk, no new synthesis
    assert abs(len(first) - len(second)) <= 2
