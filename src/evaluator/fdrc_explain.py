from __future__ import annotations

from statistics import median
from typing import Any, Callable

from .fdrc_contract import (
    _cancel_respected,
    _completed,
    _failure_values,
    yield_latency_passed,
)

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


def _applicable_rows(episodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        e for e in _rows(episodes)
        if (e.get("latency") or {}).get("yield_applicable")
    ]


def _latency_rows(episodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        e
        for e in _rows(episodes)
        if isinstance((e.get("latency") or {}).get("yield_latency_ms"), (int, float))
    ]


def _latency_metric_rows(
    episodes: list[dict[str, Any]], metric_name: str
) -> list[dict[str, Any]]:
    return [
        e
        for e in _rows(episodes)
        if isinstance((e.get("latency") or {}).get(metric_name), (int, float))
    ]


def _percentile(values: list[int | float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = round((len(ordered) - 1) * percentile)
    return float(ordered[index])


def _explain_latency_summary_metric(
    metric_key: str, episodes: list[dict[str, Any]]
) -> dict[str, Any] | None:
    parts = metric_key.split(".")
    if len(parts) != 3 or parts[0] != "latency_summary":
        return None
    metric_name, statistic = parts[1], parts[2]
    if metric_name not in {"response_latency_ms", "yield_latency_ms"}:
        return None
    if statistic not in {"count", "min_ms", "p50_ms", "p95_ms", "max_ms"}:
        return None

    row_set = _latency_metric_rows(episodes, metric_name)
    pairs = sorted(
        (
            (float((e.get("latency") or {}).get(metric_name)), str(e.get("episode_id")))
            for e in row_set
        ),
        key=lambda item: item[0],
    )
    values = [value for value, _ in pairs]
    selected_episode_ids: list[str] = []
    if not values:
        value = None
    elif statistic == "count":
        value = float(len(values))
        selected_episode_ids = [episode_id for _, episode_id in pairs]
    elif statistic == "min_ms":
        value = min(values)
        selected_episode_ids = [episode_id for latency, episode_id in pairs if latency == value]
    elif statistic == "max_ms":
        value = max(values)
        selected_episode_ids = [episode_id for latency, episode_id in pairs if latency == value]
    elif statistic == "p50_ms":
        value = _percentile(values, 0.50)
        index = round((len(values) - 1) * 0.50)
        selected_episode_ids = [pairs[index][1]]
    else:
        value = _percentile(values, 0.95)
        index = round((len(values) - 1) * 0.95)
        selected_episode_ids = [pairs[index][1]]

    denominator_episode_ids = [episode_id for _, episode_id in pairs]
    preview = ", ".join(str(round(v)) for v in values[:12])
    suffix = "..." if len(values) > 12 else ""
    display_value = round(value) if isinstance(value, (int, float)) else "N/A"
    calculation_vi = (
        f"Sắp xếp {len(values)} giá trị {metric_name} tăng dần: [{preview}{suffix}]. "
        f"{statistic} tính lại = {display_value}"
        f"{' ms' if statistic != 'count' else ''}."
    )
    unit = "count" if statistic == "count" else "ms"
    return {
        "key": metric_key,
        "supported": True,
        "scope": "all",
        "unit": unit,
        "formula_vi": f"{metric_key} = thống kê {statistic} của latency.{metric_name}",
        "row_set_label_vi": f"Episode có latency.{metric_name} là số",
        "numerator_label_vi": "Episode đại diện cho thống kê được chọn",
        "numerator": value,
        "denominator": len(values),
        "value": value,
        "numerator_episode_ids": selected_episode_ids,
        "denominator_episode_ids": denominator_episode_ids,
        "denominator_condition_vi": (
            f"Mọi FDRC episode có latency.{metric_name} là số."
        ),
        "pass_condition_vi": (
            "Metric này là thống kê phân phối, không có điều kiện pass/fail boolean."
        ),
        "evaluation_checks_vi": [
            f"latency.{metric_name}",
            "episode_id",
            "failure_types",
        ],
        "calculation_vi": calculation_vi,
        "explorer_filter": None,
    }


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
        "denominator_condition_vi": "Episode completed và có scores.final_pass khác null.",
        "pass_condition_vi": "scores.final_pass phải bằng true sau khi evaluator tổng hợp task, policy, voice và state checks.",
        "evaluation_checks_vi": [
            "scores.final_pass",
            "repair.correction_uptaken",
            "repair.old_intent_committed",
            "repair.forbidden_tool_called",
            "scores.state_match",
            "failure_types",
        ],
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
        "denominator_condition_vi": "Episode completed và có scores.final_pass khác null; không lọc fdrc_validity.",
        "pass_condition_vi": "scores.final_pass phải bằng true.",
        "evaluation_checks_vi": [
            "scores.final_pass",
            "fdrc_validity.valid",
            "failure_types",
        ],
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
        "denominator_condition_vi": "Chỉ tính episode có fdrc_validity.valid=true, completed và có scores.final_pass khác null.",
        "pass_condition_vi": "scores.final_pass phải bằng true trong tập episode hợp lệ.",
        "evaluation_checks_vi": [
            "fdrc_validity.valid",
            "scores.final_pass",
            "repair",
            "voice_events",
            "failure_types",
        ],
        "explorer_filter": {"validity": "valid", "passed": "false"},
    },
    "headline_fdrc_pass_at_1": {
        "scope": "valid",
        "row_set": _scored(_completed_rows, "operational_final_pass"),
        "predicate": lambda e: bool(e.get("scores", {}).get("operational_final_pass")),
        "unit": "rate",
        "formula_vi": "headline pass = operational_final_pass=true ÷ episode hợp lệ hoàn tất có chấm operational_final_pass",
        "row_set_label_vi": "Episode hợp lệ & hoàn tất có điểm operational_final_pass",
        "numerator_label_vi": "Episode đạt ở tầng operational (operational_final_pass = true)",
        "denominator_condition_vi": "Chỉ tính episode có fdrc_validity.valid=true, completed và có scores.operational_final_pass khác null.",
        "pass_condition_vi": "scores.operational_final_pass=true: fdrc_validity hợp lệ và không còn lỗi BLOCKING sau khi nới khớp state/tool/arg đã chuẩn hóa.",
        "evaluation_checks_vi": [
            "fdrc_validity.valid",
            "scores.operational_final_pass",
            "scores.operational_state_match",
            "scores.operational_correction_uptaken",
            "failure_types",
        ],
        "explorer_filter": {"validity": "valid"},
    },
    "yield_latency_pass_rate": {
        "scope": "all",
        "row_set": _latency_rows,
        "predicate": yield_latency_passed,
        "unit": "rate",
        "formula_vi": "yield pass = episode có yield_latency_ms và latency <= ngưỡng yield ÷ episode có yield_latency_ms",
        "row_set_label_vi": "Episode có latency.yield_latency_ms quan sát được",
        "numerator_label_vi": "Episode yield đúng hạn theo ngưỡng latency",
        "denominator_condition_vi": "Chỉ tính episode có latency.yield_latency_ms là số.",
        "pass_condition_vi": "latency.yield_latency_ms <= latency.yield_threshold_ms; nếu thiếu threshold thì mặc định 700 ms.",
        "evaluation_checks_vi": [
            "voice_events.user_interrupt_start",
            "voice_events.assistant_speech_stop",
            "latency.yield_latency_ms",
            "latency.yield_threshold_ms",
        ],
        "explorer_filter": {"failure": "YIELD_LATENCY_TOO_HIGH"},
    },
    "performance_yield_latency_pass_rate": {
        "scope": "valid",
        "row_set": _latency_rows,
        "predicate": yield_latency_passed,
        "unit": "rate",
        "formula_vi": "performance yield pass = episode hợp lệ có yield_latency_ms và latency <= ngưỡng yield ÷ episode hợp lệ có yield_latency_ms",
        "row_set_label_vi": "Episode FDRC hợp lệ có latency.yield_latency_ms",
        "numerator_label_vi": "Episode hợp lệ yield đúng hạn theo ngưỡng latency",
        "denominator_condition_vi": "Chỉ tính episode có fdrc_validity.valid=true và latency.yield_latency_ms là số.",
        "pass_condition_vi": "latency.yield_latency_ms <= latency.yield_threshold_ms; nếu thiếu threshold thì mặc định 700 ms.",
        "evaluation_checks_vi": [
            "fdrc_validity.valid",
            "latency.yield_latency_ms",
            "latency.yield_threshold_ms",
        ],
        "explorer_filter": {"validity": "valid", "failure": "YIELD_LATENCY_TOO_HIGH"},
    },
    "policy_violation_rate": {
        "scope": "all",
        "row_set": _completed_rows,
        "predicate": lambda e: "POLICY_VIOLATION" in _failure_values(e),
        "unit": "rate",
        "formula_vi": "tỷ lệ vi phạm = episode có POLICY_VIOLATION ÷ episode hoàn tất",
        "row_set_label_vi": "Episode hoàn tất (completed)",
        "numerator_label_vi": "Episode vi phạm policy (POLICY_VIOLATION)",
        "denominator_condition_vi": "Episode completed.",
        "pass_condition_vi": "Metric này đo lỗi: episode vào tử số khi failure_types chứa POLICY_VIOLATION.",
        "evaluation_checks_vi": [
            "failure_types",
            "policy_violations",
            "tool_calls",
        ],
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
        "denominator_condition_vi": "Episode completed.",
        "pass_condition_vi": "Metric này đo lỗi: episode vào tử số khi validation_errors không rỗng.",
        "evaluation_checks_vi": [
            "validation_errors",
            "tool_calls",
            "expected_tool_calls",
        ],
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
        "denominator_condition_vi": "Episode completed và có scores.state_match khác null.",
        "pass_condition_vi": "scores.state_match phải bằng true sau khi so final_state với expected_final_state.",
        "evaluation_checks_vi": [
            "expected_final_state",
            "final_state",
            "state_diff",
            "scores.state_match",
        ],
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
        "denominator_condition_vi": "Episode có object repair trong log.",
        "pass_condition_vi": "repair.old_intent_committed phải false.",
        "evaluation_checks_vi": [
            "repair.old_intent_committed",
            "tool_calls",
            "voice_events.tool_commit_allowed_after",
            "failure_types",
        ],
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
        "denominator_condition_vi": "Episode có object repair trong log.",
        "pass_condition_vi": "Metric này đo lỗi: episode vào tử số khi repair.forbidden_tool_called=true.",
        "evaluation_checks_vi": [
            "repair.forbidden_tool_called",
            "forbidden_tool_calls",
            "tool_calls",
            "failure_types",
        ],
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
        "denominator_condition_vi": "Episode có object repair trong log.",
        "pass_condition_vi": "repair.correction_uptaken phải true.",
        "evaluation_checks_vi": [
            "repair.correction_uptaken",
            "repair.final_intent",
            "expected_tool_calls",
            "tool_calls",
            "final_state",
        ],
        "explorer_filter": {"failure": "CORRECTION_NOT_UPTAKEN"},
    },
    "cancel_success_rate": {
        "scope": "all",
        "row_set": _cancel_rows,
        "predicate": _cancel_respected,
        "unit": "rate",
        "formula_vi": "cancel thành công = episode cancel không gọi tool sau lệnh hủy ÷ episode final_intent=cancel",
        "row_set_label_vi": "Episode có final_intent = cancel",
        "numerator_label_vi": "Episode cancel được tôn trọng (không attempted tool call)",
        "denominator_condition_vi": "Episode repair có repair.final_intent=cancel.",
        "pass_condition_vi": "repair.cancel_respected=true; field này chỉ true khi tool_calls rỗng, không chỉ khi tool result không mutate state.",
        "evaluation_checks_vi": [
            "repair.final_intent",
            "repair.cancel_respected",
            "repair.cancel_attempted_tool_call",
            "repair.cancel_tool_call_count",
            "repair.forbidden_tool_called",
            "tool_calls",
        ],
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
        "denominator_condition_vi": "Mọi episode thuộc track Full-Duplex Repair-to-Commit.",
        "pass_condition_vi": "fdrc_validity.valid phải bằng true.",
        "evaluation_checks_vi": [
            "fdrc_validity.valid",
            "fdrc_validity.reasons",
            "voice_events",
            "transcript",
            "tool_calls",
            "final_state",
        ],
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
        "denominator_condition_vi": "Mọi episode thuộc track Full-Duplex Repair-to-Commit.",
        "pass_condition_vi": "fdrc_validity.valid phải bằng true.",
        "evaluation_checks_vi": [
            "fdrc_validity.valid",
            "fdrc_validity.reasons",
        ],
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
        "denominator_condition_vi": "Mọi episode thuộc track Full-Duplex Repair-to-Commit.",
        "pass_condition_vi": "Episode vào tử số khi fdrc_validity.valid không true.",
        "evaluation_checks_vi": [
            "fdrc_validity.valid",
            "fdrc_validity.reasons",
        ],
        "explorer_filter": {"validity": "invalid"},
    },
    "yield_latency_p50_ms": {
        "scope": "all",
        "row_set": _latency_rows,
        "special": "latency_percentile",
        "percentile": 0.50,
        "unit": "ms",
        "formula_vi": "P50 yield latency = median của latency.yield_latency_ms trên episode có latency quan sát được sau khi sắp xếp tăng dần",
        "row_set_label_vi": "Episode có latency.yield_latency_ms quan sát được",
        "numerator_label_vi": "Giá trị median được chọn",
        "denominator_condition_vi": "Chỉ tính episode có latency.yield_latency_ms là số.",
        "pass_condition_vi": "Không có tử số boolean; metric lấy median của phân phối yield latency.",
        "evaluation_checks_vi": [
            "voice_events.user_interrupt_start",
            "voice_events.assistant_speech_stop",
            "latency.yield_latency_ms",
        ],
        "explorer_filter": None,
    },
    "yield_latency_p95_ms": {
        "scope": "all",
        "row_set": _latency_rows,
        "special": "latency_percentile",
        "percentile": 0.95,
        "unit": "ms",
        "formula_vi": "P95 yield latency = latency tại index round((n - 1) × 0.95) trên episode có latency quan sát được sau khi sắp xếp tăng dần",
        "row_set_label_vi": "Episode có latency.yield_latency_ms quan sát được",
        "numerator_label_vi": "Giá trị percentile được chọn",
        "denominator_condition_vi": "Chỉ tính episode có latency.yield_latency_ms là số.",
        "pass_condition_vi": "Không có tử số boolean; metric lấy phân vị 95 của phân phối yield latency.",
        "evaluation_checks_vi": [
            "voice_events.user_interrupt_start",
            "voice_events.assistant_speech_stop",
            "latency.yield_latency_ms",
        ],
        "explorer_filter": None,
    },
    "performance_yield_latency_p50_ms": {
        "scope": "valid",
        "row_set": _latency_rows,
        "special": "latency_percentile",
        "percentile": 0.50,
        "unit": "ms",
        "formula_vi": "Performance P50 yield latency = median của latency.yield_latency_ms trên episode hợp lệ",
        "row_set_label_vi": "Episode hợp lệ có latency.yield_latency_ms",
        "numerator_label_vi": "Giá trị median được chọn",
        "denominator_condition_vi": "Chỉ tính FDRC episode có fdrc_validity.valid=true và latency.yield_latency_ms là số.",
        "pass_condition_vi": "Không có tử số boolean; metric lấy median của phân phối yield latency hợp lệ.",
        "evaluation_checks_vi": [
            "fdrc_validity.valid",
            "latency.yield_latency_ms",
        ],
        "explorer_filter": {"validity": "valid"},
    },
    "performance_yield_latency_p95_ms": {
        "scope": "valid",
        "row_set": _latency_rows,
        "special": "latency_percentile",
        "percentile": 0.95,
        "unit": "ms",
        "formula_vi": "Performance P95 yield latency = phân vị 95 của latency.yield_latency_ms trên episode hợp lệ",
        "row_set_label_vi": "Episode hợp lệ có latency.yield_latency_ms",
        "numerator_label_vi": "Giá trị percentile được chọn",
        "denominator_condition_vi": "Chỉ tính FDRC episode có fdrc_validity.valid=true và latency.yield_latency_ms là số.",
        "pass_condition_vi": "Không có tử số boolean; metric lấy P95 của phân phối yield latency hợp lệ.",
        "evaluation_checks_vi": [
            "fdrc_validity.valid",
            "latency.yield_latency_ms",
        ],
        "explorer_filter": {"validity": "valid"},
    },
}

# pass_at_1 is an alias of fdrc_pass_at_1
_EXPLAIN_SPECS["pass_at_1"] = _EXPLAIN_SPECS["fdrc_pass_at_1"]
# performance_operational_fdrc_pass_at_1 is an alias of the headline metric
_EXPLAIN_SPECS["performance_operational_fdrc_pass_at_1"] = _EXPLAIN_SPECS[
    "headline_fdrc_pass_at_1"
]

SUPPORTED_EXPLAIN_KEYS = tuple(_EXPLAIN_SPECS.keys())


def explain_fdrc_metric(
    metric_key: str, episodes: list[dict[str, Any]]
) -> dict[str, Any] | None:
    latency_summary = _explain_latency_summary_metric(metric_key, episodes)
    if latency_summary is not None:
        return latency_summary
    spec = _EXPLAIN_SPECS.get(metric_key)
    if spec is None:
        return {"key": metric_key, "supported": False}
    scoped = _valid_only(episodes) if spec["scope"] == "valid" else list(episodes)
    row_set = spec["row_set"](scoped)
    if spec.get("special") == "latency_percentile":
        values = sorted(
            float((e.get("latency") or {}).get("yield_latency_ms"))
            for e in row_set
            if isinstance((e.get("latency") or {}).get("yield_latency_ms"), (int, float))
        )
        if not values:
            value = None
        elif spec["percentile"] == 0.50:
            value = float(median(values))
        else:
            value = _percentile(values, spec["percentile"])
        denominator_episode_ids = [str(e.get("episode_id")) for e in row_set]
        preview = ", ".join(str(round(v)) for v in values[:12])
        suffix = "..." if len(values) > 12 else ""
        calculation_vi = (
            f"Sắp xếp {len(values)} yield_latency_ms tăng dần: [{preview}{suffix}]. "
            f"Giá trị tính lại = {round(value) if value is not None else 'N/A'} ms."
        )
        return {
            "key": metric_key,
            "supported": True,
            "scope": spec["scope"],
            "unit": spec["unit"],
            "formula_vi": spec["formula_vi"],
            "row_set_label_vi": spec["row_set_label_vi"],
            "numerator_label_vi": spec["numerator_label_vi"],
            "numerator": value,
            "denominator": len(values),
            "value": value,
            "numerator_episode_ids": denominator_episode_ids,
            "denominator_episode_ids": denominator_episode_ids,
            "denominator_condition_vi": spec["denominator_condition_vi"],
            "pass_condition_vi": spec["pass_condition_vi"],
            "evaluation_checks_vi": spec["evaluation_checks_vi"],
            "calculation_vi": calculation_vi,
            "explorer_filter": spec["explorer_filter"],
        }
    predicate: Predicate = spec["predicate"]
    numerator_rows = [e for e in row_set if predicate(e)]
    denominator = len(row_set)
    numerator = len(numerator_rows)
    denominator_episode_ids = [str(e.get("episode_id")) for e in row_set]
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
        "denominator_episode_ids": denominator_episode_ids,
        "denominator_condition_vi": spec["denominator_condition_vi"],
        "pass_condition_vi": spec["pass_condition_vi"],
        "evaluation_checks_vi": spec["evaluation_checks_vi"],
        "explorer_filter": spec["explorer_filter"],
    }
