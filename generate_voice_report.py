from __future__ import annotations

import argparse
from pathlib import Path

from speech_interaction.evaluator.fdrc_evaluator import summarize_fdrc
from speech_interaction.evaluator.retention_evaluator import summarize_retention
from speech_interaction.io import read_jsonl
from speech_interaction.runner import generate_report


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a combined Vivi voice benchmark report.")
    parser.add_argument("--text-results", default="results/text_baseline/episodes.jsonl")
    parser.add_argument("--voice-results", default="results/voice_retention/episodes.jsonl")
    parser.add_argument("--fdrc-results", default="results/fdrc/episodes.jsonl")
    parser.add_argument("--output", default="speech_interaction/reports")
    args = parser.parse_args()
    retention = read_jsonl(args.text_results) + read_jsonl(args.voice_results)
    fdrc = read_jsonl(args.fdrc_results)
    generate_report(
        summarize_retention(retention),
        summarize_fdrc(fdrc),
        retention + fdrc,
        args.output,
    )
    print(f"Report written to {Path(args.output).resolve()}")


if __name__ == "__main__":
    main()
