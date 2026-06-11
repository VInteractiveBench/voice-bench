"""Cut the long in-cabin noise recordings into short, normalized segments.

The 5 `data/voice/cabin-sound/In-Vehicle_Noise_MDT0*.wav` files are ~52 min, 44.1 kHz
stereo and far too large to mix directly. This one-shot script streams each file,
downmixes to mono, resamples to 24 kHz, and writes ~5 s PCM16 segments to
`data/voice/cabin-sound/segments/`. The noise mixer then samples those segments.

Idempotent: skips if `segments/` already has files unless `--force` is passed.

Usage:
    python scripts/segment_cabin_noise.py [--segment-seconds 5] [--max-per-file 40] [--force]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from speech_interaction.audio import audio_io  # noqa: E402

CABIN_DIR = ROOT / "data" / "voice" / "cabin-sound"
SEGMENT_DIR = CABIN_DIR / "segments"


def segment_file(
    src: str | Path,
    out_dir: str | Path,
    *,
    segment_seconds: float = 5.0,
    target_sr: int = audio_io.TARGET_SR,
    max_segments: int | None = None,
    prefix: str | None = None,
) -> list[Path]:
    """Stream one WAV into normalized mono 24 kHz segments. Returns written paths."""
    import soundfile as sf

    src = Path(src)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = prefix or src.stem
    written: list[Path] = []

    with sf.SoundFile(str(src)) as handle:
        native_sr = handle.samplerate
        block_frames = int(segment_seconds * native_sr)
        index = 0
        while True:
            if max_segments is not None and index >= max_segments:
                break
            block = handle.read(frames=block_frames, dtype="float32", always_2d=False)
            if len(block) == 0:
                break
            # Drop a trailing fragment far shorter than a full segment.
            if len(block) < block_frames * 0.5 and index > 0:
                break
            mono = audio_io.to_mono(block)
            resampled = audio_io.resample(mono, native_sr, target_sr)
            index += 1
            out_path = out_dir / f"{stem}_{index:04d}.wav"
            audio_io.save_wav(out_path, resampled, target_sr)
            written.append(out_path)
    return written


def main() -> int:
    parser = argparse.ArgumentParser(description="Segment long cabin-noise WAVs.")
    parser.add_argument("--segment-seconds", type=float, default=5.0)
    parser.add_argument("--max-per-file", type=int, default=100)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    if not CABIN_DIR.exists():
        print(f"FAIL: {CABIN_DIR} not found")
        return 1

    existing = list(SEGMENT_DIR.glob("*.wav")) if SEGMENT_DIR.exists() else []
    if existing and not args.force:
        print(f"segments/ already has {len(existing)} files; use --force to rebuild.")
        return 0
    if args.force and existing:
        for path in existing:
            path.unlink()

    sources = sorted(p for p in CABIN_DIR.glob("*.wav") if p.is_file())
    if not sources:
        print(f"FAIL: no source WAVs in {CABIN_DIR}")
        return 1

    total = 0
    for src in sources:
        written = segment_file(
            src,
            SEGMENT_DIR,
            segment_seconds=args.segment_seconds,
            max_segments=args.max_per_file,
        )
        total += len(written)
        print(f"{src.name}: {len(written)} segments")
    print(f"Done. {total} segments in {SEGMENT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


