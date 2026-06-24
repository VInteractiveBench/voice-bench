from __future__ import annotations

from typing import Any, Callable

from .fdrc_contract import _cancel_respected, _completed, _failure_values

FDRC_TRACK = "full_duplex_repair_to_commit"

Predicate = Callable[[dict[str, Any]], bool]
RowSet = Callable[[list[dict[str, Any]]], list[dict[str, Any]]]


def _rows(episodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [e for e in episodes if e.get("benchmark_track") in {None, FDRC_TRACK}]


def _completed_rows(episodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [e for e in _rows(episodes) if _completed(e)]


def _repair_rows(episodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [e for e in _rows(episodes) if isinstance(e.get("repair"), dict)]


def _cancel_rows(episodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [e for e in _repair_rows(episodes) if e.get("repair", {}).get("final_intent") == "cancel"]


def _scored(row_set: RowSet, score_key: str) -> RowSet:
    return lambda episodes: [
        e for e in row_set(episodes) if e.get("scores", {}).get(score_key) is not None
    ]


def _valid_only(episodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [e for e in episodes if e.get("fdrc_validity", {}).get("valid")]


# spec: (scope, row_set, predicate, unit, formula_vi, row_set_label_vi,
#        numerator_label_vi, explorer_filter)
_EXPLAIN_SPECS: dict[str, dict[str, Any]] = {
    "fdrc_pass_at_1": {
        "scope": "all",
        "row_set": _scored(_completed_rows, "final_pass"),
        "predicate": lambda e: bool(e.get("scores", {}).get("final_pass")),
        "unit": "rate",
        "formula_vi": "pass = số episode pass toàn bộ ÷ số episode hoàn tất có chấm final_pass",
        "row_set_label_vi": "Episode hoàn tất (completed) có điểm final_pass",
        "numerator_label_vi": "Episode pass toàn bộ (final_pass = true)",
        "explorer_filter": {"passed": "false"},
    },
    "raw_fdrc_pass_at_1": {
        "scope": "all",
        "row_set": _scored(_completed_rows, "final_pass"),
        "predicate": lambda e: bool(e.get("scores", {}).get("final_pass")),
        "unit": "rate",
        "formula_vi": "raw pass = pass toàn bộ ÷ episode hoàn tất (KHÔNG lọc validity)",
        "row_set_label_vi": "Episode hoàn tất có điểm final_pass (mọi episode)",
        "numerator_label_vi": "Episode pass toàn bộ (final_pass = true)",
        "explorer_filter": {"passed": "false"},
    },
    "performance_fdrc_pass_at_1": {
        "scope": "valid",
        "row_set": _scored(_completed_rows, "final_pass"),
        "predicate": lambda e: bool(e.get("scores", {}).get("final_pass")),
        "unit": "rate",
        "formula_vi": "performance pass = pass toàn bộ ÷ episode hoàn tất, CHỈ trên episode hợp lệ",
        "row_set_label_vi": "Episode hợp lệ & hoàn tất có điểm final_pass",
        "numerator_label_vi": "Episode pass toàn bộ (final_pass = true)",
        "explorer_filter": {"validity": "valid", "passed": "false"},
    },
    "yield_latency_pass_rate": {
        "scope": "all",
        "row_set": _completed_rows,
        "predicate": lambda e: "YIELD_LATENCY_TOO_HIGH" not in _failure_values(e),
        "unit": "rate",
        "formula_vi": "yield pass = episode KHÔNG bị YIELD_LATENCY_TOO_HIGH ÷ episode hoàn tất",
        "row_set_label_vi": "Episode hoàn tất (completed)",
        "numerator_label_vi": "Episode yield đúng hạn (không có YIELD_LATENCY_TOO_HIGH)",
        "explorer_filter": {"failure": "YIELD_LATENCY_TOO_HIGH"},
    },
    "policy_violation_rate": {
        "scope": "all",
        "row_set": _completed_rows,
        "predicate": lambda e: "POLICY_VIOLATION" in _failure_values(e),
        "unit": "rate",
        "formula_vi": "tỷ lệ vi phạm = episode có POLICY_VIOLATION ÷ episode hoàn tất",
        "row_set_label_vi": "Episode hoàn tất (completed)",
        "numerator_label_vi": "Episode vi phạm policy (POLICY_VIOLATION)",
        "explorer_filter": {"failure": "POLICY_VIOLATION"},
    },
    "tool_validation_error_rate": {
        "scope": "all",
        "row_set": _completed_rows,
        "predicate": lambda e: bool(e.get("validation_errors")),
        "unit": "rate",
        "formula_vi": "tỷ lệ lỗi tool = episode có validation_errors ÷ episode hoàn tất",
        "row_set_label_vi": "Episode hoàn tất (completed)",
        "numerator_label_vi": "Episode có lỗi validation tool",
        "explorer_filter": {"validity": "invalid"},
    },
    "state_match": {
        "scope": "all",
        "row_set": _scored(_completed_rows, "state_match"),
        "predicate": lambda e: bool(e.get("scores", {}).get("state_match")),
        "unit": "rate",
        "formula_vi": "state match = episode đúng final state ÷ episode hoàn tất có chấm state_match",
        "row_set_label_vi": "Episode hoàn tất có điểm state_match",
        "numerator_label_vi": "Episode đúng final state (state_match = true)",
        "explorer_filter": {"passed": "false"},
    },
    "old_intent_suppression_rate": {
        "scope": "all",
        "row_set": _repair_rows,
        "predicate": lambda e: not bool(e.get("repair", {}).get("old_intent_committed")),
        "unit": "rate",
        "formula_vi": "chặn ý định cũ = episode KHÔNG commit ý định cũ ÷ episode có repair",
        "row_set_label_vi": "Episode có repair timeline",
        "numerator_label_vi": "Episode chặn được ý định cũ (old_intent_committed = false)",
        "explorer_filter": {"failure": "OLD_INTENT_COMMITTED"},
    },
    "forbidden_tool_call_rate": {
        "scope": "all",
        "row_set": _repair_rows,
        "predicate": lambda e: bool(e.get("repair", {}).get("forbidden_tool_called")),
        "unit": "rate",
        "formula_vi": "gọi tool bị cấm = episode gọi tool cấm ÷ episode có repair",
        "row_set_label_vi": "Episode có repair timeline",
        "numerator_label_vi": "Episode gọi tool bị cấm (forbidden_tool_called = true)",
        "explorer_filter": {"failure": "FORBIDDEN_TOOL_CALL"},
    },
    "correction_uptake_rate": {
        "scope": "all",
        "row_set": _repair_rows,
        "predicate": lambda e: bool(e.get("repair", {}).get("correction_uptaken")),
        "unit": "rate",
        "formula_vi": "tiếp nhận sửa = episode tiếp nhận ý định mới ÷ episode có repair",
        "row_set_label_vi": "Episode có repair timeline",
        "numerator_label_vi": "Episode tiếp nhận sửa (correction_uptaken = true)",
        "explorer_filter": {"failure": "CORRECTION_NOT_UPTAKEN"},
    },
    "cancel_success_rate": {
        "scope": "all",
        "row_set": _cancel_rows,
        "predicate": _cancel_respected,
        "unit": "rate",
        "formula_vi": "cancel thành công = episode cancel không tạo side effect ÷ episode final_intent=cancel",
        "row_set_label_vi": "Episode có final_intent = cancel",
        "numerator_label_vi": "Episode cancel được tôn trọng (không side effect)",
        "explorer_filter": {"failure": "CANCEL_NOT_RESPECTED"},
    },
    # NOTE: validity metrics use _rows() (track-filtered). summarize_fdrc_validity
    # does not filter by track, so values match ONLY when the caller passes
    # FDRC-track-scoped episodes (DashboardStore does this before calling).
    "fdrc_validity_rate": {
        "scope": "all",
        "row_set": _rows,
        "predicate": lambda e: bool(e.get("fdrc_validity", {}).get("valid")),
        "unit": "rate",
        "formula_vi": "validity = episode hợp lệ ÷ tổng episode",
        "row_set_label_vi": "Tổng episode trong track",
        "numerator_label_vi": "Episode hợp lệ (fdrc_validity.valid = true)",
        "explorer_filter": {"validity": "invalid"},
    },
    "valid_episode_count": {
        "scope": "all",
        "row_set": _rows,
        "predicate": lambda e: bool(e.get("fdrc_validity", {}).get("valid")),
        "unit": "count",
        "formula_vi": "đếm số episode hợp lệ",
        "row_set_label_vi": "Tổng episode trong track",
        "numerator_label_vi": "Episode hợp lệ",
        "explorer_filter": {"validity": "valid"},
    },
    "invalid_episode_count": {
        "scope": "all",
        "row_set": _rows,
        "predicate": lambda e: not bool(e.get("fdrc_validity", {}).get("valid")),
        "unit": "count",
        "formula_vi": "đếm số episode invalid",
        "row_set_label_vi": "Tổng episode trong track",
        "numerator_label_vi": "Episode invalid",
        "explorer_filter": {"validity": "invalid"},
    },
}

# pass_at_1 is an alias of fdrc_pass_at_1
_EXPLAIN_SPECS["pass_at_1"] = _EXPLAIN_SPECS["fdrc_pass_at_1"]

SUPPORTED_EXPLAIN_KEYS = tuple(_EXPLAIN_SPECS.keys())


def explain_fdrc_metric(
    metric_key: str, episodes: list[dict[str, Any]]
) -> dict[str, Any] | None:
    spec = _EXPLAIN_SPECS.get(metric_key)
    if spec is None:
        return {"key": metric_key, "supported": False}
    scoped = _valid_only(episodes) if spec["scope"] == "valid" else list(episodes)
    row_set = spec["row_set"](scoped)
    predicate: Predicate = spec["predicate"]
    numerator_rows = [e for e in row_set if predicate(e)]
    denominator = len(row_set)
    numerator = len(numerator_rows)
    if spec["unit"] == "count":
        value: float | None = numerator
    else:
        value = (numerator / denominator) if denominator else None
    # numerator_episode_ids are bare id strings; the dashboard service layer
    # (DashboardStore.explain_metric) enriches them into numerator_episodes objects.
    return {
        "key": metric_key,
        "supported": True,
        "scope": spec["scope"],
        "unit": spec["unit"],
        "formula_vi": spec["formula_vi"],
        "row_set_label_vi": spec["row_set_label_vi"],
        "numerator_label_vi": spec["numerator_label_vi"],
        "numerator": numerator,
        "denominator": denominator,
        "value": value,
        "numerator_episode_ids": [str(e.get("episode_id")) for e in numerator_rows],
        "explorer_filter": spec["explorer_filter"],
    }
