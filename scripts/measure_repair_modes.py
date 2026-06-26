"""Per-repair-mode and per-domain FDRC pass-rate breakdown for a saved run.

Usage:
    C:\\Python314\\python -m scripts.measure_repair_modes results/fdrc_openai_full

Reads episodes.jsonl, groups by repair_mode from overlay_snapshot or episode
fallback, and prints pass/total per repair mode and per domain.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path


def _repair_mode(episode: dict) -> str:
    snap = episode.get("overlay_snapshot") or {}
    return snap.get("repair_mode") or episode.get("repair_mode") or "unknown"


def _domain(episode: dict) -> str:
    snap = episode.get("overlay_snapshot") or {}
    return snap.get("domain") or episode.get("domain") or "unknown"


def _breakdown(episodes: list[dict], key_fn) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = defaultdict(lambda: {"pass": 0, "total": 0})
    for episode in episodes:
        key = key_fn(episode)
        out[key]["total"] += 1
        if episode.get("scores", {}).get("final_pass"):
            out[key]["pass"] += 1
    return {key: dict(counts) for key, counts in out.items()}


def repair_mode_breakdown(episodes: list[dict]) -> dict[str, dict[str, int]]:
    return _breakdown(episodes, _repair_mode)


def domain_breakdown(episodes: list[dict]) -> dict[str, dict[str, int]]:
    return _breakdown(episodes, _domain)


def _load_episodes(run_dir: str) -> list[dict]:
    path = Path(run_dir) / "episodes.jsonl"
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8-sig").splitlines()
        if line.strip()
    ]


def _print_breakdown(title: str, breakdown: dict[str, dict[str, int]]) -> None:
    print(title)
    for key, counts in sorted(breakdown.items()):
        rate = counts["pass"] / counts["total"] if counts["total"] else 0.0
        print(f"{key:24s} {counts['pass']:>3}/{counts['total']:<3} ({rate:.0%})")


def main() -> None:
    run_dir = sys.argv[1] if len(sys.argv) > 1 else "results/fdrc_openai_full"
    episodes = _load_episodes(run_dir)
    _print_breakdown("repair_mode", repair_mode_breakdown(episodes))
    print()
    _print_breakdown("domain", domain_breakdown(episodes))


if __name__ == "__main__":
    main()
