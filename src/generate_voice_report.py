from __future__ import annotations

import argparse
from pathlib import Path

from src.evaluator.fdrc_evaluator import summarize_fdrc
from src.evaluator.retention_evaluator import summarize_retention
from src.io import read_jsonl
from src.runner import generate_report


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a combined Vivi voice benchmark report.")
    parser.add_argument("--text-results", default="results/provider/text_baseline/episodes.jsonl")
    parser.add_argument("--voice-results", default="results/provider/voice_retention/episodes.jsonl")
    parser.add_argument("--fdrc-results", default="results/provider/fdrc/episodes.jsonl")
    parser.add_argument("--output", default="src/reports")
    parser.add_argument("--allow-reference", action="store_true")
    args = parser.parse_args()
    retention = read_jsonl(args.text_results) + read_jsonl(args.voice_results)
    fdrc = read_jsonl(args.fdrc_results)
    generate_report(
        summarize_retention(retention),
        summarize_fdrc(fdrc),
        retention + fdrc,
        args.output,
        allow_reference=args.allow_reference,
    )
    print(f"Report written to {Path(args.output).resolve()}")


if __name__ == "__main__":
    main()
