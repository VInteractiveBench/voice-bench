from __future__ import annotations

from statistics import median
from typing import Any


FDRC_REQUIRED_METRICS = [
    "episode_count",
    "completed_episode_count",
    "partial_episode_count",
    "fdrc_pass_at_1",
    "pass_at_1",
    "yield_latency_p50_ms",
    "yield_latency_p95_ms",
    "yield_latency_pass_rate",
    "policy_violation_rate",
    "state_match",
    "tool_validation_error_rate",
    "old_intent_suppression_rate",
    "forbidden_tool_call_rate",
    "correction_uptake_rate",
]

FDRC_NULLABLE_METRICS = {
    "cancel_success_rate": "no_cancel_cases",
}


def _failure_values(episode: dict[str, Any]) -> set[str]:
    return {str(value) for value in episode.get("failure_types", []) or []}


def _safe_number(value: Any) -> int | float | None:
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _rate(rows: list[dict[str, Any]], predicate) -> float | None:
    return sum(1 for row in rows if predicate(row)) / len(rows) if rows else None


def _score_rate(rows: list[dict[str, Any]], score_key: str) -> float | None:
    scored = [
        row
        for row in rows
        if row.get("scores", {}).get(score_key) is not None
    ]
    return _rate(scored, lambda row: bool(row.get("scores", {}).get(score_key)))


def _cancel_respected(episode: dict[str, Any]) -> bool:
    repair = episode.get("repair", {})
    if episode.get("tool_calls") or repair.get("cancel_attempted_tool_call"):
        return False
    if "cancel_respected" in repair:
        return bool(repair.get("cancel_respected"))
    return not bool(repair.get("forbidden_tool_called"))


def _percentile(values: list[int | float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = round((len(ordered) - 1) * percentile)
    return float(ordered[index])


def _completed(episode: dict[str, Any]) -> bool:
    return (
        episode.get("scores", {}).get("final_pass") is not None
        and not episode.get("dashboard_reevaluation_error")
    )


def summarize_fdrc_contract(episodes: list[dict[str, Any]]) -> dict[str, Any]:
    rows = [
        episode
        for episode in episodes
        if episode.get("benchmark_track") in {None, "full_duplex_repair_to_commit"}
    ]
    completed_rows = [episode for episode in rows if _completed(episode)]
    partial_rows = [episode for episode in rows if not _completed(episode)]
    latency_values = [
        value
        for value in (
            _safe_number(episode.get("latency", {}).get("yield_latency_ms"))
            for episode in rows
        )
        if value is not None
    ]
    repair_rows = [episode for episode in rows if isinstance(episode.get("repair"), dict)]
    cancel_rows = [
        episode for episode in repair_rows if episode.get("repair", {}).get("final_intent") == "cancel"
    ]
    metrics: dict[str, Any] = {
        "episode_count": len(rows),
        "completed_episode_count": len(completed_rows),
        "partial_episode_count": len(partial_rows),
        "fdrc_pass_at_1": _score_rate(completed_rows, "final_pass"),
        "pass_at_1": _score_rate(completed_rows, "final_pass"),
        "yield_latency_p50_ms": median(latency_values) if latency_values else None,
        "yield_latency_p95_ms": _percentile(latency_values, 0.95),
        "yield_latency_pass_rate": _rate(
            completed_rows,
            lambda episode: "YIELD_LATENCY_TOO_HIGH" not in _failure_values(episode),
        ),
        "policy_violation_rate": _rate(
            completed_rows,
            lambda episode: "POLICY_VIOLATION" in _failure_values(episode),
        ),
        "state_match": _score_rate(completed_rows, "state_match"),
        "tool_validation_error_rate": _rate(
            completed_rows,
            lambda episode: bool(episode.get("validation_errors")),
        ),
        "old_intent_suppression_rate": _rate(
            repair_rows,
            lambda episode: not bool(episode.get("repair", {}).get("old_intent_committed")),
        ),
        "forbidden_tool_call_rate": _rate(
            repair_rows,
            lambda episode: bool(episode.get("repair", {}).get("forbidden_tool_called")),
        ),
        "correction_uptake_rate": _rate(
            repair_rows,
            lambda episode: bool(episode.get("repair", {}).get("correction_uptaken")),
        ),
        "cancel_success_rate": _rate(
            cancel_rows,
            _cancel_respected,
        ),
    }
    denominators = {
        "episode_count": 1,
        "completed_episode_count": len(rows),
        "partial_episode_count": len(rows),
        "fdrc_pass_at_1": len(completed_rows),
        "pass_at_1": len(completed_rows),
        "yield_latency_p50_ms": len(rows),
        "yield_latency_p95_ms": len(rows),
        "yield_latency_pass_rate": len(completed_rows),
        "policy_violation_rate": len(completed_rows),
        "state_match": len(completed_rows),
        "tool_validation_error_rate": len(completed_rows),
        "old_intent_suppression_rate": len(repair_rows),
        "forbidden_tool_call_rate": len(repair_rows),
        "correction_uptake_rate": len(repair_rows),
        "cancel_success_rate": len(cancel_rows),
    }
    null_reasons: dict[str, dict[str, Any]] = {}
    for metric, reason in FDRC_NULLABLE_METRICS.items():
        if metrics.get(metric) is None:
            null_reasons[metric] = {
                "null_reason": reason,
                "denominator": denominators.get(metric, 0),
            }
    contract_violations = [
        {
            "metric": metric,
            "reason": "required_metric_null",
            "denominator": denominators.get(metric, 0),
        }
        for metric in FDRC_REQUIRED_METRICS
        if metrics.get(metric) is None and denominators.get(metric, 0) > 0
    ]
    if contract_violations:
        status = "invalid"
    elif not rows or partial_rows:
        status = "partial"
    elif metrics["pass_at_1"] == 1.0:
        status = "completed"
    else:
        status = "failed_evaluated"
    metrics["metric_contract"] = {
        "benchmark_track": "full_duplex_repair_to_commit",
        "required_metrics": FDRC_REQUIRED_METRICS,
        "nullable_metrics": FDRC_NULLABLE_METRICS,
        "denominators": denominators,
        "null_reasons": null_reasons,
        "violations": contract_violations,
        "benchmark_status": status,
    }
    return metrics
