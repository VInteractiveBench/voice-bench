from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from src.dashboard.service import (
    DashboardStore,
    FDRC_TRACK,
    _evaluation_view,
)
from src.evaluator.fdrc_contract import (
    FDRC_NULLABLE_METRICS,
    FDRC_REQUIRED_METRICS,
)
from src.evaluator.fdrc_evaluator import summarize_fdrc


CONTRACT_METRICS = [
    *FDRC_REQUIRED_METRICS,
    *FDRC_NULLABLE_METRICS.keys(),
    "metric_contract",
]


def _store(results_dir: str | Path) -> DashboardStore:
    return DashboardStore(Path(results_dir))


def evaluated_fdrc_episodes(run_id: str, results_dir: str | Path = "results") -> list[dict[str, Any]]:
    store = _store(results_dir)
    _, _, episodes, _ = store._load_run(run_id)
    evaluated = _evaluation_view(episodes)
    return [
        episode for episode in evaluated if episode.get("benchmark_track") == FDRC_TRACK
    ]


def evaluator_metrics(run_id: str, results_dir: str | Path = "results") -> dict[str, Any]:
    return summarize_fdrc(evaluated_fdrc_episodes(run_id, results_dir))


def service_metrics(run_id: str, results_dir: str | Path = "results") -> dict[str, Any]:
    return _store(results_dir).run_summary(run_id, track=FDRC_TRACK)["metrics"]


def comparable_fdrc_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    return {key: metrics.get(key) for key in CONTRACT_METRICS}


def compare_layers(run_id: str, results_dir: str | Path = "results") -> dict[str, Any]:
    evaluator = comparable_fdrc_metrics(evaluator_metrics(run_id, results_dir))
    service = comparable_fdrc_metrics(service_metrics(run_id, results_dir))
    mismatches = [
        {"metric": key, "evaluator": evaluator.get(key), "service": service.get(key)}
        for key in CONTRACT_METRICS
        if evaluator.get(key) != service.get(key)
    ]
    return {
        "run_id": run_id,
        "matched": not mismatches,
        "mismatches": mismatches,
        "evaluator": evaluator,
        "service": service,
    }


def debug_rows(run_id: str, results_dir: str | Path = "results") -> list[dict[str, Any]]:
    rows = []
    for episode in evaluated_fdrc_episodes(run_id, results_dir):
        repair = episode.get("repair") or {}
        failures = [str(value) for value in episode.get("failure_types", []) or []]
        missing_observed = repair.get("missing_observed_events") or []
        rows.append(
            {
                "episode_id": episode.get("episode_id"),
                "completed": episode.get("scores", {}).get("final_pass") is not None,
                "observed_events_ok": not bool(missing_observed),
                "yield_ms": episode.get("latency", {}).get("yield_latency_ms"),
                "final_state_match": _score_bool(episode, "state_match"),
                "correction_uptake": repair.get("correction_uptaken"),
                "old_intent_suppression": not bool(repair.get("old_intent_committed")),
                "forbidden_tool_call": bool(repair.get("forbidden_tool_called")),
                "validation_error": bool(episode.get("validation_errors")),
                "fail_reasons": failures,
            }
        )
    return rows


def format_debug_table(rows: list[dict[str, Any]]) -> str:
    headers = [
        "episode_id",
        "completed",
        "observed_events_ok",
        "yield_ms",
        "final_state_match",
        "old_intent_suppressed",
        "forbidden_tool",
        "validation_error",
        "fail_reasons",
    ]
    table_rows = [
        [
            str(row.get("episode_id") or ""),
            _bool_text(row.get("completed")),
            _bool_text(row.get("observed_events_ok")),
            _value_text(row.get("yield_ms")),
            _bool_text(row.get("final_state_match")),
            _bool_text(row.get("old_intent_suppression")),
            _bool_text(row.get("forbidden_tool_call")),
            _bool_text(row.get("validation_error")),
            ", ".join(row.get("fail_reasons") or []),
        ]
        for row in rows
    ]
    widths = [
        max(len(header), *(len(row[index]) for row in table_rows))
        if table_rows
        else len(header)
        for index, header in enumerate(headers)
    ]
    lines = [" | ".join(header.ljust(widths[index]) for index, header in enumerate(headers))]
    lines.append("-+-".join("-" * width for width in widths))
    lines.extend(
        " | ".join(value.ljust(widths[index]) for index, value in enumerate(row))
        for row in table_rows
    )
    return "\n".join(lines)


def benchmark_report(run_id: str, results_dir: str | Path = "results") -> dict[str, Any]:
    episodes = evaluated_fdrc_episodes(run_id, results_dir)
    metrics = summarize_fdrc(episodes)
    failures = Counter(
        failure for episode in episodes for failure in episode.get("failure_types", []) or []
    )
    return {
        "run_id": run_id,
        "benchmark_track": FDRC_TRACK,
        "metrics": comparable_fdrc_metrics(metrics),
        "failure_counts": [
            {"failure_type": str(key), "count": count}
            for key, count in failures.most_common()
        ],
        "episodes": debug_rows(run_id, results_dir),
    }


def write_benchmark_report(
    run_id: str,
    results_dir: str | Path = "results",
    output_dir: str | Path | None = None,
) -> tuple[Path, Path]:
    target = Path(output_dir) if output_dir is not None else Path(results_dir) / run_id
    target.mkdir(parents=True, exist_ok=True)
    report = benchmark_report(run_id, results_dir)
    json_path = target / "benchmark_report.json"
    md_path = target / "benchmark_report.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(_format_markdown_report(report), encoding="utf-8")
    return json_path, md_path


def _format_markdown_report(report: dict[str, Any]) -> str:
    metrics = report["metrics"]
    contract = metrics.get("metric_contract") or {}
    lines = [
        f"# FDRC Benchmark Report: {report['run_id']}",
        "",
        f"Benchmark status: `{contract.get('benchmark_status')}`",
        "",
        "## Metrics",
        "",
        "| Metric | Value |",
        "|---|---:|",
    ]
    for key, value in metrics.items():
        if key == "metric_contract":
            continue
        lines.append(f"| {key} | {_value_text(value)} |")
    lines.extend(
        [
            "",
            "## Null Reasons",
            "",
            "| Metric | Reason | Denominator |",
            "|---|---|---:|",
        ]
    )
    for key, reason in (contract.get("null_reasons") or {}).items():
        lines.append(
            f"| {key} | {reason.get('null_reason')} | {reason.get('denominator')} |"
        )
    lines.extend(
        [
            "",
            "## Failure Counts",
            "",
            "| Failure Type | Count |",
            "|---|---:|",
        ]
    )
    for row in report["failure_counts"]:
        lines.append(f"| {row['failure_type']} | {row['count']} |")
    lines.extend(
        [
            "",
            "## Episode Evidence",
            "",
            "| Episode | Completed | Observed Events OK | Yield ms | Final State Match | Correction Uptake | Old Intent Suppressed | Forbidden Tool | Validation Error | Fail Reasons |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|",
        ]
    )
    for row in report["episodes"]:
        lines.append(
            "| "
            + " | ".join(
                [
                    str(row.get("episode_id")),
                    _bool_text(row.get("completed")),
                    _bool_text(row.get("observed_events_ok")),
                    _value_text(row.get("yield_ms")),
                    _bool_text(row.get("final_state_match")),
                    _bool_text(row.get("correction_uptake")),
                    _bool_text(row.get("old_intent_suppression")),
                    _bool_text(row.get("forbidden_tool_call")),
                    _bool_text(row.get("validation_error")),
                    ", ".join(row.get("fail_reasons") or []),
                ]
            )
            + " |"
        )
    return "\n".join(lines) + "\n"


def _score_bool(episode: dict[str, Any], key: str) -> bool | None:
    value = episode.get("scores", {}).get(key)
    return None if value is None else bool(value)


def _bool_text(value: Any) -> str:
    if value is None:
        return "null"
    return "true" if bool(value) else "false"


def _value_text(value: Any) -> str:
    return "null" if value is None else str(value)
