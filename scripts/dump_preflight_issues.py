"""Enumerate all preflight issues for an overlay file.

Usage:
    C:\\Python314\\python -m scripts.dump_preflight_issues fdrc_golden_enriched_v2_90.jsonl
"""
from __future__ import annotations

import collections
import sys

from src.io import load_base_tasks, load_overlays
from src.schema import validate_overlay


def main() -> None:
    path = sys.argv[1] if len(sys.argv) > 1 else "fdrc_golden_enriched_v2_90.jsonl"
    tasks = load_base_tasks()
    overlays = load_overlays(path)
    issues = []
    for index, overlay in enumerate(overlays):
        for issue in validate_overlay(overlay, tasks, f"overlay[{index}]"):
            issues.append(
                (
                    index,
                    issue["field"],
                    issue["reason"],
                    issue.get("value"),
                )
            )
    print(f"total issues: {len(issues)} across {len({i for i, *_ in issues})} overlays")
    by_issue = collections.Counter(
        (field.split(".")[-1], reason, str(value))
        for _, field, reason, value in issues
    )
    for key, count in by_issue.most_common():
        print(f"  {count:>3}  {key}")


if __name__ == "__main__":
    main()
