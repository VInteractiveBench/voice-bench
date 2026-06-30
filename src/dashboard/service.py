from __future__ import annotations

import json
import subprocess
import sys
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.io import load_base_tasks, load_overlays
from src.evaluator.fdrc_evaluator import evaluate_fdrc_episode, summarize_fdrc
from src.evaluator.fdrc_contract import summarize_fdrc_contract
from src.evaluator.fdrc_explain import explain_fdrc_metric
from src.evaluator.policy_gating_explain import explain_policy_gating_metric
from src.evaluator.policy_gating_evaluator import (
    evaluate_policy_gating_episode,
    summarize_policy_gating,
)
from src.runner import episode_set_hash


ROOT_DIR = Path(__file__).resolve().parents[2]
POLICY_TRACK = "voice_policy_command_gating"
FDRC_TRACK = "full_duplex_repair_to_commit"
PRIORITY_TIMELINE_EVENTS = {
    "assistant_speech_start",
    "user_interrupt_start",
    "assistant_yielded",
    "assistant_should_yield_by",
    "tool_commit_allowed_after",
    "tool_call",
}
METRIC_NUMERATOR_IS_FAILURE = {
    "forbidden_tool_call_rate",
    "hallucinated_tool_rate",
    "invalid_episode_count",
    "out_of_scope_tool_call_rate",
    "policy_violation_rate",
    "tool_validation_error_rate",
}
METRIC_SAMPLE_LIMIT = 10

RUN_JOBS: dict[str, dict[str, Any]] = {}

BENCHMARK_LABELS = {
    POLICY_TRACK: "Policy-Grounded Voice Command Gating",
    FDRC_TRACK: "Full-Duplex Repair-to-Commit",
}

RUN_PRESETS = {
    "policy_gating_reference": {
        "label": "Policy gating reference-agent",
        "benchmark_track": POLICY_TRACK,
        "script": "run_policy_gating.py",
        "args": ["--reference-agent"],
        "default_output_prefix": "dashboard_policy_gating_reference",
    },
    "policy_gating_openai": {
        "label": "Policy gating OpenAI realtime",
        "benchmark_track": POLICY_TRACK,
        "script": "run_policy_gating.py",
        "args": ["--agent", "openai_realtime"],
        "default_output_prefix": "dashboard_policy_gating_openai",
    },
    "fdrc_reference": {
        "label": "FDRC reference-agent",
        "benchmark_track": FDRC_TRACK,
        "script": "run_fdrc.py",
        "args": ["--reference-agent"],
        "default_output_prefix": "dashboard_fdrc_reference",
    },
    "fdrc_openai": {
        "label": "FDRC OpenAI realtime",
        "benchmark_track": FDRC_TRACK,
        "script": "run_fdrc.py",
        "args": ["--agent", "openai_realtime"],
        "default_output_prefix": "dashboard_fdrc_openai",
    },
}

DOMAIN_LABELS = {
    "automotive": "Automotive",
    "navigation": "Navigation",
    "media_phone": "Media & Phone",
}

SPEED_LABELS = {
    "slow": "Chậm",
    "normal": "Bình thường",
    "fast": "Nhanh",
}

TRACK_DESCRIPTIONS = {
    POLICY_TRACK: (
        "Đo xem Vivi có chọn đúng hành vi execute/clarify/refuse/defer theo "
        "policy và trạng thái xe khi nhận lệnh giọng nói trong cabin."
    ),
    FDRC_TRACK: (
        "Đo khả năng nhường lời khi user chen ngang, tiếp nhận lệnh sửa/hủy, "
        "chặn ý định cũ và chỉ commit ý định cuối cùng."
    ),
}

METRIC_GROUPS = [
    {
        "id": "overview",
        "label": "Overview",
        "metric_keys": [
            "pass_at_1",
            "episode_count",
            "completed_episode_count",
            "partial_episode_count",
        ],
    },
    {
        "id": "tool_state",
        "label": "Tool / State",
        "metric_keys": [
            "tool_exact_match",
            "argument_exact_match",
            "state_match",
            "tool_validation_error_rate",
            "out_of_scope_tool_call_rate",
            "hallucinated_tool_rate",
        ],
    },
    {"id": "policy", "label": "Policy", "metric_keys": ["policy_violation_rate"]},
    {
        "id": "policy_gating",
        "label": "Policy-Grounded Voice Command Gating",
        "metric_keys": [
            "policy_compliance_rate",
            "forbidden_tool_call_rate",
            "clarification_precision",
            "clarification_recall",
            "state_conditioned_decision_accuracy",
            "final_state_correctness",
            "response_honesty_rate",
            "tool_argument_accuracy",
        ],
    },
    {
        "id": "fdrc",
        "label": "Sửa lệnh full-duplex",
        "metric_keys": [
            # Single FDRC pass score (operational tier — the fair model-quality number).
            "operational_fdrc_pass_at_1",
            "operational_state_match",
            "operational_tool_match",
            "operational_argument_match",
            "operational_correction_uptake_rate",
            "fdrc_validity_rate",
            "valid_episode_count",
            "invalid_episode_count",
            "infra_error_count",
            "old_intent_suppression_rate",
            "forbidden_tool_call_rate",
            "cancel_success_rate",
            "yield_latency_pass_rate",
        ],
    },
    {
        "id": "latency",
        "label": "Độ trễ",
        "metric_keys": [
            "yield_latency_p50_ms",
            "yield_latency_p95_ms",
            "performance_yield_latency_p50_ms",
            "performance_yield_latency_p95_ms",
            "performance_yield_latency_pass_rate",
            "latency_summary.*",
        ],
    },
    {
        "id": "contract",
        "label": "Contract / Data Quality",
        "metric_keys": [
            "metric_contract.benchmark_status",
            "metric_contract.violations",
            "metric_contract.null_reasons",
            "metrics_hash_valid",
            "parse_errors",
        ],
    },
]

METRIC_REGISTRY = {
    "pass_at_1": ("Pass tổng", "Tỷ lệ episode pass toàn bộ tiêu chí.", "rate", "overview"),
    "episode_count": ("Số episode", "Tổng số episode trong run đang xem.", "count", "overview"),
    "completed_episode_count": ("Episode hoàn tất", "Số episode có score hợp lệ.", "count", "overview"),
    "partial_episode_count": ("Episode thiếu dữ liệu", "Số episode chưa đủ dữ liệu để tính metric hoàn chỉnh.", "count", "overview"),
    "tool_exact_match": ("Khớp tool", "Tỷ lệ episode gọi đúng chuỗi tool expected.", "rate", "tool_state"),
    "argument_exact_match": ("Khớp argument", "Tỷ lệ episode truyền đúng argument tool expected.", "rate", "tool_state"),
    "state_match": ("Khớp trạng thái", "Tỷ lệ episode có final state khớp expected.", "rate", "tool_state"),
    "tool_validation_error_rate": ("Lỗi validation tool", "Tỷ lệ episode có lỗi schema, argument hoặc contract tool.", "rate", "tool_state"),
    "out_of_scope_tool_call_rate": ("Tool ngoài phạm vi", "Tỷ lệ episode gọi official tool ngoài MVP scope.", "rate", "tool_state"),
    "hallucinated_tool_rate": ("Tool không whitelist", "Tỷ lệ episode gọi tool không nằm trong whitelist.", "rate", "tool_state"),
    "policy_violation_rate": ("Vi phạm policy", "Tỷ lệ episode vi phạm policy benchmark.", "rate", "policy"),
    "policy_compliance_rate": ("Tuân thủ policy", "Tỷ lệ episode chọn đúng execute/clarify/refuse/defer.", "rate", "policy_gating"),
    "forbidden_tool_call_rate": ("Gọi tool bị cấm", "Tỷ lệ episode policy-sensitive có gọi forbidden tool (càng thấp càng tốt).", "rate", "policy_gating"),
    "clarification_precision": ("Độ chính xác hỏi lại", "correct_clarifications / all_clarifications_made.", "rate", "policy_gating"),
    "clarification_recall": ("Độ phủ hỏi lại", "required_clarifications_made / all_cases_requiring_clarification.", "rate", "policy_gating"),
    "state_conditioned_decision_accuracy": ("Đúng theo trạng thái xe", "Tỷ lệ quyết định đúng trên các episode state-conditioned.", "rate", "policy_gating"),
    "final_state_correctness": ("Đúng final state", "Tỷ lệ episode có final state khớp expected.", "rate", "policy_gating"),
    "response_honesty_rate": ("Phản hồi trung thực", "Tỷ lệ phản hồi nhất quán với tool execution thực tế.", "rate", "policy_gating"),
    "tool_argument_accuracy": ("Đúng argument tool", "Tỷ lệ argument tool đúng trên các execute case.", "rate", "policy_gating"),
    "fdrc_pass_at_1": ("Đạt FDRC", "Tỷ lệ episode FDRC đạt toàn bộ tiêu chí.", "rate", "fdrc"),
    "headline_fdrc_pass_at_1": ("Điểm Tổng Đạt FDRC", "Tỷ lệ đạt ở tầng operational trên episode hợp lệ (gated theo reportable). Trùng với Điểm Tổng Đạt FDRC; giữ cho tương thích.", "rate", "fdrc"),
    "performance_operational_fdrc_pass_at_1": ("Điểm Tổng Đạt FDRC", "Alias của headline_fdrc_pass_at_1.", "rate", "fdrc"),
    "performance_fdrc_pass_at_1": ("Đạt FDRC siết", "Cổng siết: pass khi không có BẤT KỲ failure type nào, chỉ trên episode hợp lệ. Cực kỳ khắt khe (~4-5% trên run thật) — số phụ để soi lỗi, không phải điểm chất lượng.", "rate", "fdrc"),
    "raw_fdrc_pass_at_1": ("Đạt FDRC thô", "Tỷ lệ đạt trên toàn bộ episode, dùng để điều tra lỗi.", "rate", "fdrc"),
    "fdrc_validity_rate": ("Độ hợp lệ FDRC", "Tỷ lệ episode có đủ bằng chứng để chấm kết quả chính thức.", "rate", "fdrc"),
    "valid_episode_count": ("Episode hợp lệ", "Số episode FDRC đủ bằng chứng để chấm kết quả chính thức.", "count", "fdrc"),
    "invalid_episode_count": ("Episode không hợp lệ", "Số episode FDRC thiếu bằng chứng hoặc sai bản ghi/tool/trạng thái.", "count", "fdrc"),
    "validity_failure_counts": ("Lý do không hợp lệ", "Các lý do khiến episode không đủ điều kiện chấm chính thức.", "count", "fdrc"),
    "infra_error_count": ("Lỗi hạ tầng", "Số episode chết vì lỗi mạng/DNS (transport) — model chưa từng được đo; bị loại khỏi mẫu số validity, KHÔNG tính là model fail.", "count", "fdrc"),
    "measured_episode_count": ("Episode đo được", "Số episode thực sự chạy tới được model (đã loại lỗi hạ tầng); mẫu số của độ hợp lệ FDRC.", "count", "fdrc"),
    "correction_uptake_rate": ("Tiếp nhận lệnh sửa", "Tỷ lệ episode tiếp nhận đúng ý định cuối cùng sau khi sửa.", "rate", "fdrc"),
    "operational_fdrc_pass_at_1": ("Điểm Tổng Đạt FDRC", "Tỷ lệ episode đạt FDRC (khớp tool/arg đã chuẩn hóa giá trị, chỉ tính lỗi blocking) — điểm chất lượng mô hình; reference-agent đạt 100% chứng minh evaluator nhất quán.", "rate", "fdrc"),
    "operational_state_match": ("Đúng final state", "Tỷ lệ khớp final state sau chuẩn hóa casefold/bỏ dấu.", "rate", "fdrc"),
    "operational_tool_match": ("Khớp tool", "Mọi expected call đều có call khớp; cho phép call thừa trong scope.", "rate", "fdrc"),
    "operational_argument_match": ("Đúng argument", "Argument khớp sau chuẩn hóa, chỉ xét call đã gọi đúng tên tool.", "rate", "fdrc"),
    "operational_correction_uptake_rate": ("Tiếp nhận lệnh sửa", "Đạt khi final state (đã chuẩn hóa) tới đúng mục tiêu đã sửa.", "rate", "fdrc"),
    "old_intent_suppression_rate": ("Chặn lệnh cũ", "Tỷ lệ episode không thực thi ý định ban đầu sau khi người dùng sửa.", "rate", "fdrc"),
    "forbidden_tool_call_rate": ("Gọi tool cấm", "Tỷ lệ episode có gọi tool bị cấm.", "rate", "fdrc"),
    "cancel_success_rate": ("Hủy lệnh đúng", "Tỷ lệ ca hủy không attempted tool call sau lệnh hủy.", "rate", "fdrc"),
    "yield_latency_pass_rate": ("Nhường lời đạt", "Tỷ lệ episode nhường lời trong ngưỡng cho phép.", "rate", "fdrc"),
    "yield_latency_p50_ms": ("P50 nhường lời", "Trung vị độ trễ nhường lời sau khi user chen ngang.", "ms", "latency"),
    "yield_latency_p95_ms": ("P95 nhường lời", "Phân vị 95 của độ trễ nhường lời.", "ms", "latency"),
    "performance_yield_latency_p50_ms": ("P50 nhường lời hợp lệ", "P50 độ trễ nhường lời chỉ trên episode hợp lệ.", "ms", "latency"),
    "performance_yield_latency_p95_ms": ("P95 nhường lời hợp lệ", "P95 độ trễ nhường lời chỉ trên episode hợp lệ.", "ms", "latency"),
    "performance_yield_latency_pass_rate": ("Nhường lời đạt hợp lệ", "Tỷ lệ nhường lời đạt chỉ trên episode hợp lệ.", "rate", "latency"),
    "metric_contract.benchmark_status": ("Trạng thái contract", "Trạng thái hợp lệ của metric contract.", "text", "contract"),
    "metric_contract.violations": ("Vi phạm contract", "Số metric bắt buộc bị thiếu hoặc không hợp lệ.", "count", "contract"),
    "metric_contract.null_reasons": ("Metric nullable rỗng", "Số metric nullable đang không có mẫu hợp lệ.", "count", "contract"),
    "metrics_hash_valid": ("Hash metrics hợp lệ", "metrics.json có khớp episode_set_hash của episode set đang xem không.", "boolean", "contract"),
    "parse_errors": ("Lỗi đọc dữ liệu", "Số lỗi parse khi đọc metrics.json hoặc episodes.jsonl.", "count", "contract"),
}

DASHBOARD_HIDDEN_METRICS_BY_TRACK = {
    FDRC_TRACK: {
        # fdrc_pass_at_1 is the contract alias for raw_fdrc_pass_at_1 in the
        # FDRC summary. Keeping both in the payload is useful for compatibility,
        # but showing both as cards creates a duplicate KPI.
        "fdrc_pass_at_1",
        # validity_failure_counts is a list-valued diagnostic flattened into a
        # count for the catalog; beside invalid_episode_count it reads as the
        # same KPI. Keep it in metrics/detail payloads, hide it from the grid.
        "validity_failure_counts",
    },
}


class RunNotFound(Exception):
    pass


def _read_json(path: Path) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    try:
        return json.loads(path.read_text(encoding="utf-8")), []
    except Exception as exc:
        return None, [{"file": str(path), "line": None, "error": str(exc)}]


def _read_jsonl(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception as exc:
        return [], [{"file": str(path), "line": None, "error": str(exc)}]
    for index, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except Exception as exc:
            errors.append({"file": str(path), "line": index, "error": str(exc)})
            continue
        if isinstance(item, dict):
            rows.append(item)
        else:
            errors.append(
                {"file": str(path), "line": index, "error": "JSONL row is not an object"}
            )
    return rows, errors


def _read_top_level_yaml_fields(path: Path) -> dict[str, str]:
    fields: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        if not raw_line or raw_line.startswith((" ", "-")) or ":" not in raw_line:
            continue
        key, value = raw_line.split(":", 1)
        value = value.strip().strip("'\"")
        if value:
            fields[key.strip()] = value
    return fields


def _mtime_iso(paths: list[Path]) -> str | None:
    existing = [path for path in paths if path.exists()]
    if not existing:
        return None
    ts = max(path.stat().st_mtime for path in existing)
    return datetime.fromtimestamp(ts, timezone.utc).isoformat()


def _score_pass(episode: dict[str, Any]) -> bool | None:
    value = episode.get("scores", {}).get("final_pass")
    if value is None:
        return None
    return bool(value)


def _safe_number(value: Any) -> int | float | None:
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _rate(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _bool_rate(rows: list[dict[str, Any]], predicate) -> float | None:
    return sum(1 for row in rows if predicate(row)) / len(rows) if rows else None


def _values(rows: list[dict[str, Any]], field: str) -> list[str]:
    return sorted({str(row[field]) for row in rows if row.get(field) not in (None, "")})


def _audio_condition_for_difficulty(
    audio_condition_id: str | None = None,
    difficulty: str | None = None,
) -> str | None:
    if audio_condition_id:
        return audio_condition_id
    if difficulty:
        return FDRC_DIFFICULTY_TO_AUDIO.get(difficulty, difficulty)
    return None


def _run_kind(run_id: str) -> str:
    if run_id.startswith("check_") or "reference" in run_id:
        return "reference"
    if run_id.startswith("_plan_check_") or run_id.startswith("_impl_check_"):
        return "internal"
    if run_id.endswith("_sample") or "_sample" in run_id:
        return "sample"
    return "benchmark"


def _data_provenance(run_id: str, episodes: list[dict[str, Any]]) -> str:
    if not episodes:
        return "unknown"
    if any(row.get("is_reference") for row in episodes):
        return "reference"
    explicit_kinds = {row.get("run_kind") for row in episodes if row.get("run_kind")}
    if len(explicit_kinds) == 1:
        kind = next(iter(explicit_kinds))
        if kind in {"provider", "reference", "internal", "sample"}:
            return str(kind)
    has_provider_identity = any(
        row.get("agent") or row.get("model")
        for row in episodes
    )
    if has_provider_identity:
        return "provider"
    if _run_kind(run_id) in {"reference", "internal", "sample"}:
        return _run_kind(run_id)
    return "synthetic_reference"


def _provenance_label(provenance: str) -> str:
    labels = {
        "provider": "Kết quả provider/model thật",
        "synthetic_reference": "Dữ liệu reference-agent tổng hợp",
        "reference": "Dữ liệu reference-agent",
        "internal": "Dữ liệu kiểm tra nội bộ",
        "sample": "Dữ liệu sample",
        "unknown": "Không rõ nguồn dữ liệu",
    }
    return labels.get(provenance, provenance)


def _provenance_warning(provenance: str) -> str | None:
    if provenance == "provider":
        return None
    if provenance == "synthetic_reference":
        return (
            "Run này không có agent/model trong episode log; các số 100% nhiều khả năng "
            "đến từ reference-agent dùng để kiểm tra evaluator, không phải performance thật."
        )
    if provenance == "reference":
        return "Run reference-agent chỉ kiểm tra benchmark/evaluator, không phải performance model thật."
    if provenance == "internal":
        return "Run nội bộ phục vụ kiểm tra triển khai, không nên dùng để báo cáo performance."
    if provenance == "sample":
        return "Run sample dùng để demo/smoke test, không đủ đại diện để kết luận performance."
    return "Không xác định được nguồn dữ liệu của run này."


def _track_label(track: str | None) -> str:
    return BENCHMARK_LABELS.get(str(track), str(track or "Không rõ benchmark"))


def _dominant_track(episodes: list[dict[str, Any]]) -> str | None:
    counter = Counter(
        str(row.get("benchmark_track"))
        for row in episodes
        if row.get("benchmark_track")
    )
    return counter.most_common(1)[0][0] if counter else None


def _metric_from_episodes(episodes: list[dict[str, Any]], key: str) -> float | None:
    score_map = {
        "pass_at_1": "final_pass",
        "tool_exact_match": "tool_exact_match",
        "argument_exact_match": "argument_exact_match",
        "state_match": "state_match",
    }
    score_key = score_map.get(key)
    if not score_key:
        return None
    rows = [
        episode
        for episode in episodes
        if episode.get("scores", {}).get(score_key) is not None
    ]
    return _rate(
        sum(1 for episode in rows if bool(episode.get("scores", {}).get(score_key))),
        len(rows),
    )


def _percentile(values: list[int | float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = round((len(ordered) - 1) * percentile)
    return float(ordered[index])


def _summarize_from_episodes(
    episodes: list[dict[str, Any]], track: str | None = None
) -> dict[str, Any]:
    if track:
        episodes = [episode for episode in episodes if episode.get("benchmark_track") == track]
    metrics: dict[str, Any] = {
        "pass_at_1": _metric_from_episodes(episodes, "pass_at_1"),
        "tool_exact_match": _metric_from_episodes(episodes, "tool_exact_match"),
        "argument_exact_match": _metric_from_episodes(episodes, "argument_exact_match"),
        "state_match": _metric_from_episodes(episodes, "state_match"),
        "policy_violation_rate": _bool_rate(
            episodes, lambda episode: "POLICY_VIOLATION" in (episode.get("failure_types") or [])
        ),
        "tool_validation_error_rate": _bool_rate(
            episodes, lambda episode: bool(episode.get("validation_errors"))
        ),
        "out_of_scope_tool_call_rate": _bool_rate(
            episodes,
            lambda episode: "OUT_OF_SCOPE_TOOL_CALL" in (episode.get("failure_types") or []),
        ),
        "hallucinated_tool_rate": _bool_rate(
            episodes,
            lambda episode: "TOOL_NOT_IN_WHITELIST" in (episode.get("failure_types") or []),
        ),
    }
    tracks = set(_values(episodes, "benchmark_track"))
    if POLICY_TRACK in tracks:
        policy_rows = [
            episode for episode in episodes if episode.get("benchmark_track") == POLICY_TRACK
        ]
        metrics.update(summarize_policy_gating(policy_rows))
    if FDRC_TRACK in tracks:
        fdrc_rows = [
            episode for episode in episodes if episode.get("benchmark_track") == FDRC_TRACK
        ]
        metrics.update(summarize_fdrc(fdrc_rows))
    return metrics


def _first_event_time_after(
    events: list[dict[str, Any]], event_type: str, after_ms: int | None
) -> int | None:
    return next(
        (
            event.get("t_ms")
            for event in events
            if event.get("type") == event_type
            and isinstance(event.get("t_ms"), int)
            and (after_ms is None or event.get("t_ms", -1) >= after_ms)
        ),
        None,
    )


def _fdrc_voice_events_for_evaluation(
    episode: dict[str, Any], overlay: dict[str, Any]
) -> list[dict[str, Any]]:
    events = [
        {**event, "source": event.get("source") or "expected"}
        for event in overlay.get("voice_timeline", [])
        if isinstance(event, dict)
    ]
    normalized = [
        event for event in episode.get("normalized_events", []) if isinstance(event, dict)
    ]
    for event in normalized:
        event_type = event.get("type")
        t_ms = event.get("t_ms")
        if not isinstance(t_ms, int):
            continue
        if event_type == "assistant_speech_start":
            events.append(
                {"event": "assistant_speech_start", "t_ms": t_ms, "source": "observed"}
            )
        elif event_type == "assistant_speech_stop":
            events.append(
                {"event": "assistant_speech_stop", "t_ms": t_ms, "source": "observed"}
            )
        elif event_type == "user_audio_chunk_sent" and event.get("overlap"):
            events.append(
                {"event": "user_interrupt_start", "t_ms": t_ms, "source": "observed"}
            )
            events.append(
                {"event": "repair_audio_start", "t_ms": t_ms, "source": "observed"}
            )
    interrupt = next(
        (
            event["t_ms"]
            for event in events
            if event.get("event") == "user_interrupt_start"
            and event.get("source") == "observed"
            and isinstance(event.get("t_ms"), int)
        ),
        None,
    )
    repair_transcript = _first_event_time_after(normalized, "repair_transcript_done", interrupt)
    if repair_transcript is None:
        repair_transcript = _first_event_time_after(normalized, "user_transcript_done", interrupt)
    if repair_transcript is not None and not any(
        event.get("event") == "repair_transcript_done"
        and event.get("source") == "observed"
        for event in events
    ):
        events.append(
            {
                "event": "repair_transcript_done",
                "t_ms": repair_transcript,
                "source": "observed",
            }
        )
    speech_stop = _first_event_time_after(normalized, "assistant_speech_stop", interrupt)
    if interrupt is not None and speech_stop is not None:
        events.append(
            {"event": "assistant_yielded", "t_ms": speech_stop, "source": "observed"}
        )
    return sorted(events, key=lambda event: event.get("t_ms", 0))


def _evaluation_view(episodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    tasks = load_base_tasks()
    overlays = {row["speech_overlay_id"]: row for row in load_overlays()}
    evaluated: list[dict[str, Any]] = []
    for episode in episodes:
        row = dict(episode)
        # Prefer the overlay snapshot carried by the episode (self-describing runs);
        # fall back to the default overlays file for legacy episodes without one.
        overlay = row.get("overlay_snapshot") or overlays.get(row.get("speech_overlay_id"))
        task = tasks.get(row.get("base_task_id"))
        if overlay is None or task is None:
            evaluated.append(row)
            continue
        if row.get("run_kind") is None and (row.get("agent") or row.get("model")):
            row["run_kind"] = "provider"
            row["is_reference"] = False
        try:
            if row.get("benchmark_track") == FDRC_TRACK:
                if not (row.get("is_reference") or row.get("run_kind") in {"reference", "sample", "internal"}):
                    row["voice_events"] = _fdrc_voice_events_for_evaluation(row, overlay)
                row = evaluate_fdrc_episode(row, overlay, task)
            elif row.get("benchmark_track") == POLICY_TRACK:
                row = evaluate_policy_gating_episode(row, overlay, task)
        except Exception as exc:
            row.setdefault("failure_types", []).append("DASHBOARD_REEVALUATION_ERROR")
            row["primary_failure_type"] = row.get("primary_failure_type") or "DASHBOARD_REEVALUATION_ERROR"
            row["dashboard_reevaluation_error"] = str(exc)
        row["failure_types"] = [str(failure) for failure in (row.get("failure_types") or [])]
        evaluated.append(row)
    return evaluated


def _group_pass_rate(episodes: list[dict[str, Any]], field: str) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for episode in episodes:
        key = episode.get(field)
        if key not in (None, ""):
            groups[str(key)].append(episode)
    rows = []
    for key, group in sorted(groups.items()):
        passed = sum(1 for episode in group if _score_pass(episode) is True)
        total = sum(1 for episode in group if _score_pass(episode) is not None)
        rows.append({"key": key, "passed": passed, "total": total, "rate": _rate(passed, total)})
    return rows


def _failure_counts(episodes: list[dict[str, Any]], primary: bool = False) -> list[dict[str, Any]]:
    counter: Counter[str] = Counter()
    for episode in episodes:
        if primary:
            value = episode.get("primary_failure_type")
            if value:
                counter[str(value)] += 1
        else:
            for failure in episode.get("failure_types", []) or []:
                counter[str(failure)] += 1
    return [{"key": key, "count": count} for key, count in counter.most_common()]


def _latency_distribution(episodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for episode in episodes:
        latency = episode.get("latency", {}) if isinstance(episode.get("latency"), dict) else {}
        for key in ("response_latency_ms", "yield_latency_ms"):
            value = _safe_number(latency.get(key))
            if value is not None:
                rows.append({"episode_id": episode.get("episode_id"), "metric": key, "value": value})
    return rows


def _latency_summary(episodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = _latency_distribution(episodes)
    by_metric: dict[str, list[int | float]] = defaultdict(list)
    for row in rows:
        by_metric[row["metric"]].append(row["value"])
    result = []
    for metric, values in sorted(by_metric.items()):
        result.append(
            {
                "metric": metric,
                "count": len(values),
                "min_ms": min(values),
                "p50_ms": _percentile(values, 0.5),
                "p95_ms": _percentile(values, 0.95),
                "max_ms": max(values),
            }
        )
    return result


def _top_latency_episodes(
    episodes: list[dict[str, Any]],
    metric: str = "yield_latency_ms",
    limit: int = 5,
) -> list[dict[str, Any]]:
    rows = []
    for episode in episodes:
        latency = episode.get("latency", {}) if isinstance(episode.get("latency"), dict) else {}
        value = _safe_number(latency.get(metric))
        if value is None:
            continue
        rows.append(
            {
                "episode_id": episode.get("episode_id"),
                "domain": episode.get("domain"),
                "mode": episode.get("mode"),
                "primary_failure_type": episode.get("primary_failure_type"),
                "value": value,
            }
        )
    return sorted(rows, key=lambda row: row["value"], reverse=True)[:limit]


def _metric_meta(key: str) -> tuple[str, str, str, str]:
    if key in METRIC_REGISTRY:
        return METRIC_REGISTRY[key]
    if key.startswith("latency_summary."):
        parts = key.split(".")
        metric = parts[1] if len(parts) > 1 else "latency"
        statistic = parts[2] if len(parts) > 2 else "value"
        unit = "count" if statistic == "count" else "ms"
        return (
            f"{metric} {statistic}",
            "Thống kê phân phối latency được derive từ episode logs.",
            unit,
            "latency",
        )
    return (key, "Metric được trả về từ evaluator hoặc dashboard derivation.", "number", "overview")


def _short_json(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float, str)):
        return str(value)
    try:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    except TypeError:
        text = str(value)
    return text if len(text) <= 140 else text[:137] + "..."


def _field(label: str, value: Any) -> dict[str, str]:
    return {"label": label, "value": _short_json(value)}


def _policy_evidence_fields(metric_key: str, episode: dict[str, Any]) -> list[dict[str, str]]:
    pg = episode.get("policy_gating") if isinstance(episode.get("policy_gating"), dict) else {}
    fields = [
        _field("expected_behavior", pg.get("expected_behavior")),
        _field("agent_decision", pg.get("decision")),
        _field("decision_correct", pg.get("decision_correct")),
    ]
    if metric_key == "forbidden_tool_call_rate":
        fields.extend(
            [
                _field("is_policy_sensitive", pg.get("is_policy_sensitive")),
                _field("forbidden_called", pg.get("forbidden_called")),
                _field("tool_calls", episode.get("tool_calls", [])),
            ]
        )
    elif metric_key in {"clarification_precision", "clarification_recall"}:
        fields.extend(
            [
                _field("requires_clarification", pg.get("requires_clarification")),
                _field("clarification_made", pg.get("clarification_made")),
                _field("clarification_correct", pg.get("clarification_correct")),
            ]
        )
    elif metric_key == "state_conditioned_decision_accuracy":
        fields.extend(
            [
                _field("state_pair_id", pg.get("state_pair_id")),
                _field("initial_state", episode.get("initial_state", {})),
            ]
        )
    elif metric_key == "final_state_correctness":
        fields.extend(
            [
                _field("state_match", episode.get("scores", {}).get("state_match")),
                _field("state_diff", episode.get("state_diff")),
            ]
        )
    elif metric_key == "response_honesty_rate":
        fields.extend(
            [
                _field("response_honest", pg.get("response_honest")),
                _field("tool_calls", episode.get("tool_calls", [])),
            ]
        )
    elif metric_key == "tool_argument_accuracy":
        fields.extend(
            [
                _field("expected_tools", pg.get("expected_tools", [])),
                _field("tool_calls", episode.get("tool_calls", [])),
            ]
        )
    if episode.get("failure_types"):
        fields.append(_field("failure_types", episode.get("failure_types")))
    return fields


def _fdrc_evidence_fields(metric_key: str, episode: dict[str, Any]) -> list[dict[str, str]]:
    repair = episode.get("repair") if isinstance(episode.get("repair"), dict) else {}
    latency = episode.get("latency") if isinstance(episode.get("latency"), dict) else {}
    validity = episode.get("fdrc_validity") if isinstance(episode.get("fdrc_validity"), dict) else {}
    fields = [
        _field("final_pass", episode.get("scores", {}).get("final_pass")),
        _field("state_match", episode.get("scores", {}).get("state_match")),
    ]
    if metric_key in {
        "headline_fdrc_pass_at_1",
        "performance_operational_fdrc_pass_at_1",
        "operational_fdrc_pass_at_1",
    }:
        scores = episode.get("scores", {}) if isinstance(episode.get("scores"), dict) else {}
        fields.extend(
            [
                _field("operational_final_pass", scores.get("operational_final_pass")),
                _field("operational_state_match", scores.get("operational_state_match")),
                _field("operational_correction_uptaken", scores.get("operational_correction_uptaken")),
                _field("failure_types", episode.get("failure_types", [])),
            ]
        )
    elif metric_key in {"fdrc_pass_at_1", "pass_at_1", "raw_fdrc_pass_at_1", "performance_fdrc_pass_at_1"}:
        fields.extend(
            [
                _field("correction_uptaken", repair.get("correction_uptaken")),
                _field("old_intent_committed", repair.get("old_intent_committed")),
                _field("forbidden_tool_called", repair.get("forbidden_tool_called")),
                _field("failure_types", episode.get("failure_types", [])),
            ]
        )
    elif metric_key in {
        "yield_latency_p50_ms",
        "yield_latency_p95_ms",
        "performance_yield_latency_p50_ms",
        "performance_yield_latency_p95_ms",
    } or metric_key.startswith("latency_summary."):
        latency_metric = (
            metric_key.split(".")[1]
            if metric_key.startswith("latency_summary.") and len(metric_key.split(".")) > 1
            else "yield_latency_ms"
        )
        fields.extend(
            [
                _field(latency_metric, latency.get(latency_metric)),
                _field("yield_latency_ms", latency.get("yield_latency_ms")),
                _field("response_latency_ms", latency.get("response_latency_ms")),
                _field("fdrc_valid", validity.get("valid")),
                _field("validity_reasons", validity.get("reasons", [])),
            ]
        )
    elif metric_key in {"yield_latency_pass_rate", "performance_yield_latency_pass_rate"}:
        fields.extend(
            [
                _field("yield_latency_ms", latency.get("yield_latency_ms")),
                _field("fdrc_valid", validity.get("valid")),
                _field("failure_types", episode.get("failure_types", [])),
            ]
        )
    elif metric_key == "policy_violation_rate":
        fields.extend(
            [
                _field("policy_violations", episode.get("policy_violations", [])),
                _field("failure_types", episode.get("failure_types", [])),
            ]
        )
    elif metric_key == "tool_validation_error_rate":
        fields.extend(
            [
                _field("validation_errors", episode.get("validation_errors", [])),
                _field("tool_calls", episode.get("tool_calls", [])),
            ]
        )
    elif metric_key == "state_match":
        fields.extend(
            [
                _field("state_diff", episode.get("state_diff")),
                _field("final_state", episode.get("final_state", {})),
            ]
        )
    elif metric_key in {"old_intent_suppression_rate", "forbidden_tool_call_rate", "correction_uptake_rate", "cancel_success_rate"}:
        fields.extend(
            [
                _field("final_intent", repair.get("final_intent")),
                _field("correction_uptaken", repair.get("correction_uptaken")),
                _field("old_intent_committed", repair.get("old_intent_committed")),
                _field("forbidden_tool_called", repair.get("forbidden_tool_called")),
                _field("cancel_respected", repair.get("cancel_respected")),
                _field("cancel_attempted_tool_call", repair.get("cancel_attempted_tool_call")),
                _field("cancel_tool_call_count", repair.get("cancel_tool_call_count")),
                _field(
                    "cancel_blocked_tool_call_count",
                    repair.get("cancel_blocked_tool_call_count"),
                ),
                _field("tool_calls", episode.get("tool_calls", [])),
            ]
        )
    elif metric_key in {"fdrc_validity_rate", "valid_episode_count", "invalid_episode_count"}:
        fields.extend(
            [
                _field("fdrc_valid", validity.get("valid")),
                _field("validity_reasons", validity.get("reasons", [])),
            ]
        )
    return fields


def _explain_evidence_rows(
    metric_key: str,
    selected_track: str | None,
    explanation: dict[str, Any],
    by_id: dict[str, dict[str, Any]],
    *,
    limit: int = 12,
) -> list[dict[str, Any]]:
    numerator_ids = [str(value) for value in explanation.get("numerator_episode_ids", [])]
    denominator_ids = [str(value) for value in explanation.get("denominator_episode_ids", [])]
    numerator_set = set(numerator_ids)
    ordered_ids: list[str] = []
    for episode_id in [*numerator_ids, *denominator_ids]:
        if episode_id not in ordered_ids and episode_id in by_id:
            ordered_ids.append(episode_id)
        if len(ordered_ids) >= limit:
            break
    rows = []
    for episode_id in ordered_ids:
        episode = by_id.get(episode_id, {})
        fields = (
            _policy_evidence_fields(metric_key, episode)
            if selected_track == POLICY_TRACK
            else _fdrc_evidence_fields(metric_key, episode)
        )
        rows.append(
            {
                "episode_id": episode_id,
                "base_task_id": episode.get("base_task_id"),
                "domain": episode.get("domain"),
                "accent_region": episode.get("accent_region"),
                "speech_speed": episode.get("speech_speed"),
                "passed": _score_pass(episode),
                "fdrc_valid": bool(episode.get("fdrc_validity", {}).get("valid")),
                "in_numerator": episode_id in numerator_set,
                "fields": fields,
            }
        )
    return rows


def _explain_sample_rows(
    metric_key: str,
    selected_track: str | None,
    episode_ids: list[str],
    by_id: dict[str, dict[str, Any]],
    *,
    limit: int | None = METRIC_SAMPLE_LIMIT,
) -> list[dict[str, Any]]:
    rows = []
    seen: set[str] = set()
    for episode_id in episode_ids:
        if episode_id in seen or episode_id not in by_id:
            continue
        seen.add(episode_id)
        episode = by_id[episode_id]
        fields = (
            _policy_evidence_fields(metric_key, episode)
            if selected_track == POLICY_TRACK
            else _fdrc_evidence_fields(metric_key, episode)
        )
        rows.append(
            {
                "episode_id": episode_id,
                "base_task_id": episode.get("base_task_id"),
                "domain": episode.get("domain"),
                "accent_region": episode.get("accent_region"),
                "speech_speed": episode.get("speech_speed"),
                "passed": _score_pass(episode),
                "fdrc_valid": bool(episode.get("fdrc_validity", {}).get("valid")),
                "fields": fields,
            }
        )
        if limit is not None and len(rows) >= limit:
            break
    return rows


def _flatten_metrics(metrics: dict[str, Any], latency_summary: list[dict[str, Any]]) -> dict[str, Any]:
    flat: dict[str, Any] = {
        key: value
        for key, value in metrics.items()
        if key not in {"decision_confusion_matrix", "state_pairs", "metric_contract", "run_metadata"}
        and not isinstance(value, (dict, list))
    }
    contract = metrics.get("metric_contract")
    if isinstance(contract, dict):
        flat["metric_contract.benchmark_status"] = contract.get("benchmark_status")
        flat["metric_contract.violations"] = len(contract.get("violations") or [])
        flat["metric_contract.null_reasons"] = len(contract.get("null_reasons") or {})
    if isinstance(metrics.get("validity_failure_counts"), list):
        flat["validity_failure_counts"] = sum(
            int(row.get("count", 0))
            for row in metrics["validity_failure_counts"]
            if isinstance(row, dict)
        )
    for row in latency_summary:
        metric = row.get("metric")
        if not metric:
            continue
        for statistic in ("count", "min_ms", "p50_ms", "p95_ms", "max_ms"):
            flat[f"latency_summary.{metric}.{statistic}"] = row.get(statistic)
    return flat


def _metric_group_applies(group_id: str, selected_track: str | None) -> bool:
    policy_only = {"policy_gating"}
    # Latency here means interruption/yield latency, an FDRC-only concept; the
    # policy-gating track has no yield events so those metrics would be null.
    fdrc_only = {"fdrc", "latency"}
    if selected_track == POLICY_TRACK and group_id in fdrc_only:
        return False
    if selected_track == FDRC_TRACK and group_id in policy_only:
        return False
    return True


def _catalog_keys(flat_metrics: dict[str, Any], selected_track: str | None) -> list[str]:
    ordered: list[str] = []
    hidden = DASHBOARD_HIDDEN_METRICS_BY_TRACK.get(str(selected_track), set())
    for group in METRIC_GROUPS:
        if not _metric_group_applies(group["id"], selected_track):
            continue
        for key in group["metric_keys"]:
            if key in hidden:
                continue
            if key.endswith(".*"):
                prefix = key[:-1]
                ordered.extend(
                    sorted(
                        item
                        for item in flat_metrics
                        if item.startswith(prefix) and item not in hidden
                    )
                )
            elif key not in ordered:
                ordered.append(key)
    for key in sorted(flat_metrics):
        if (
            key not in hidden
            and key not in ordered
            and not isinstance(flat_metrics.get(key), (dict, list))
        ):
            ordered.append(key)
    return ordered


def _metric_status(key: str, value: Any, nullable: bool, contract_violations: set[str]) -> str:
    if key in contract_violations:
        return "invalid"
    if value is None:
        return "nullable_null" if nullable else "missing"
    return "ok"


def _synth_null_reason(key: str, metrics: dict[str, Any]) -> str:
    """Reason code for a None metric that has no contract-provided null_reason.

    Keeps N/A cells auditable: performance_* metrics are gated off until the run
    is reportable (validity >= 90%), everything else is simply absent data.
    """
    if key.startswith("performance_") or key == "headline_fdrc_pass_at_1":
        status = str(metrics.get("reportability_status") or "")
        if status and not status.startswith("REPORTABLE"):
            return "not_reportable_validity"
    return "no_data"


GOOD_HIGH_METRICS = {
    "fdrc_pass_at_1",
    "pass_at_1",
    "raw_fdrc_pass_at_1",
    "performance_fdrc_pass_at_1",
    "headline_fdrc_pass_at_1",
    "performance_operational_fdrc_pass_at_1",
    "operational_fdrc_pass_at_1",
    "tool_exact_match",
    "argument_exact_match",
    "state_match",
    "policy_compliance_rate",
    "clarification_precision",
    "clarification_recall",
    "state_conditioned_decision_accuracy",
    "final_state_correctness",
    "response_honesty_rate",
    "tool_argument_accuracy",
    "old_intent_suppression_rate",
    "correction_uptake_rate",
    "cancel_success_rate",
    "yield_latency_pass_rate",
    "performance_yield_latency_pass_rate",
    "fdrc_validity_rate",
}

FDRC_DIFFICULTIES = [
    {"id": "easy", "label": "Dễ", "audio_condition_id": "clean"},
    {"id": "medium", "label": "Trung bình", "audio_condition_id": "cabin_noise"},
    {"id": "hard", "label": "Khó", "audio_condition_id": "interaction_stress"},
]
FDRC_DIFFICULTY_TO_AUDIO = {
    row["id"]: row["audio_condition_id"] for row in FDRC_DIFFICULTIES
}
FDRC_COMPARE_AUDIO_CONDITIONS = [
    row["audio_condition_id"] for row in FDRC_DIFFICULTIES
]

BAD_HIGH_METRICS = {
    "policy_violation_rate",
    "tool_validation_error_rate",
    "out_of_scope_tool_call_rate",
    "hallucinated_tool_rate",
    "forbidden_tool_call_rate",
}

METRIC_PLAIN_MEANINGS = {
    "pass_at_1": "Cho biết tỷ lệ episode đạt toàn bộ tiêu chí chấm chính của track đang xem.",
    "episode_count": "Tổng số episode trong run hoặc lát cắt hiện tại.",
    "completed_episode_count": "Số episode có đủ dữ liệu để evaluator đưa ra điểm hoàn chỉnh.",
    "partial_episode_count": "Số episode thiếu dữ liệu hoặc bị lỗi nên kết quả chỉ nên dùng để chẩn đoán.",
    "tool_exact_match": "Đo agent có gọi đúng tool mà kịch bản yêu cầu hay không.",
    "argument_exact_match": "Đo agent có truyền đúng tham số quan trọng vào tool hay không.",
    "state_match": "Đo trạng thái cuối của xe/hệ thống có khớp trạng thái kỳ vọng hay không.",
    "tool_validation_error_rate": "Tỷ lệ episode có lỗi schema, tham số tool hoặc kết quả tool không hợp lệ.",
    "out_of_scope_tool_call_rate": "Tỷ lệ episode gọi tool nằm ngoài phạm vi benchmark cho phép.",
    "hallucinated_tool_rate": "Tỷ lệ episode gọi tool không có trong whitelist, biểu hiện agent bịa capability.",
    "policy_violation_rate": "Tỷ lệ episode vi phạm policy hoặc quyết định sai ràng buộc an toàn/ngữ cảnh.",
    "policy_compliance_rate": "Đo agent có chọn đúng hành động execute, clarify, refuse hoặc defer theo policy hay không.",
    "forbidden_tool_call_rate": "Đo mức độ agent gọi tool bị cấm trong các tình huống nhạy cảm; càng thấp càng tốt.",
    "clarification_precision": "Trong các lần agent hỏi lại, tỷ lệ câu hỏi thật sự cần thiết và đúng mục tiêu.",
    "clarification_recall": "Trong các tình huống bắt buộc phải hỏi lại, tỷ lệ agent đã hỏi lại đúng.",
    "state_conditioned_decision_accuracy": "Đo agent có đổi quyết định đúng theo trạng thái xe khác nhau cho cùng một lệnh hay không.",
    "final_state_correctness": "Đo kết quả cuối cùng sau tool/decision có làm hệ thống ở đúng trạng thái kỳ vọng hay không.",
    "response_honesty_rate": "Đo phản hồi của agent có trung thực với việc tool thật sự đã chạy hay bị chặn hay không.",
    "tool_argument_accuracy": "Đo từng tham số expected trong execute case có được truyền đúng giá trị hay không.",
    "fdrc_pass_at_1": "Tỷ lệ episode Full-Duplex đạt toàn bộ tiêu chí sửa lệnh và commit ý định cuối.",
    "raw_fdrc_pass_at_1": "Tỷ lệ đạt FDRC trên toàn bộ episode, kể cả episode thiếu bằng chứng.",
    "operational_fdrc_pass_at_1": "Điểm Tổng Đạt FDRC: tỷ lệ episode đạt FDRC (khớp tool/arg đã chuẩn hóa giá trị, chỉ tính lỗi blocking) trên episode hợp lệ. Đây là điểm chất lượng mô hình; reference-agent đạt 100% chứng minh evaluator nhất quán.",
    "headline_fdrc_pass_at_1": "Trùng Điểm Tổng Đạt FDRC (bản gated theo reportable); giữ cho tương thích.",
    "performance_operational_fdrc_pass_at_1": "Alias của headline_fdrc_pass_at_1.",
    "performance_fdrc_pass_at_1": "Cổng siết: episode chỉ đạt khi KHÔNG có bất kỳ failure type nào, tính trên episode hợp lệ. Rất khắt khe (~4-5% trên run thật) nên là số phụ để soi lỗi, không phải điểm chất lượng.",
    "fdrc_validity_rate": "Tỷ lệ episode FDRC có đủ transcript, timing, tool và state evidence để chấm chính thức.",
    "valid_episode_count": "Số episode FDRC đủ điều kiện dùng cho performance chính thức.",
    "invalid_episode_count": "Số episode FDRC thiếu bằng chứng hoặc sai log nên không nên dùng để kết luận performance.",
    "validity_failure_counts": "Số loại lỗi validity xuất hiện trong run, dùng để tìm nguyên nhân dữ liệu không reportable.",
    "correction_uptake_rate": "Tỷ lệ episode agent tiếp nhận đúng lệnh sửa cuối cùng sau khi người dùng chen ngang.",
    "old_intent_suppression_rate": "Tỷ lệ episode agent không thực thi ý định cũ sau khi người dùng đã sửa hoặc hủy.",
    "cancel_success_rate": "Tỷ lệ ca hủy được tôn trọng bằng cách không attempted tool call sau lệnh hủy.",
    "yield_latency_pass_rate": "Tỷ lệ episode agent nhường lời trong ngưỡng latency cho phép khi người dùng chen ngang.",
    "yield_latency_p50_ms": "Độ trễ nhường lời trung vị; một nửa episode có latency thấp hơn hoặc bằng số này.",
    "yield_latency_p95_ms": "Độ trễ nhường lời ở phân vị 95; phản ánh tail latency khó chịu với người dùng.",
    "performance_yield_latency_p50_ms": "P50 latency chỉ tính trên episode FDRC hợp lệ.",
    "performance_yield_latency_p95_ms": "P95 latency chỉ tính trên episode FDRC hợp lệ.",
    "performance_yield_latency_pass_rate": "Tỷ lệ nhường lời đạt ngưỡng chỉ tính trên episode FDRC hợp lệ.",
    "metric_contract.benchmark_status": "Trạng thái tổng thể của metric contract sau khi kiểm tra đủ/thiếu dữ liệu.",
    "metric_contract.violations": "Số vi phạm contract metric, thường là metric bắt buộc bị thiếu hoặc không hợp lệ.",
    "metric_contract.null_reasons": "Số metric nullable đang N/A kèm lý do hợp lệ.",
    "metrics_hash_valid": "Cho biết metrics.json có khớp tập episode đang xem hay không.",
    "parse_errors": "Số lỗi đọc JSON/JSONL khi dashboard nạp dữ liệu.",
}


def _metric_direction(key: str) -> str:
    base = key.split(".", 1)[0]
    if key in GOOD_HIGH_METRICS or base in GOOD_HIGH_METRICS:
        return "higher_is_better"
    if key in BAD_HIGH_METRICS or base in BAD_HIGH_METRICS:
        return "lower_is_better"
    if key.endswith("_p50_ms") or key.endswith("_p95_ms") or key.endswith("_latency_ms"):
        return "lower_is_better"
    return "neutral"


def _metric_value_text(value: Any, unit: str) -> str:
    if value is None:
        return "N/A"
    if isinstance(value, bool):
        return "đúng" if value else "sai"
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return str(value)
    if unit == "rate":
        return f"{value * 100:.1f}%"
    if unit == "ms":
        return f"{round(value)} ms"
    if unit == "count":
        return str(round(value))
    return f"{value:.3g}"


def _metric_result_comment(
    key: str,
    value: Any,
    unit: str,
    *,
    denominator: Any = None,
    null_reason: str | None = None,
    status: str | None = None,
) -> str:
    label, _, _, _ = _metric_meta(key)
    if value is None:
        reason = null_reason or "không có đủ dữ liệu"
        return f"Chưa có kết luận cho {label}: {reason}."
    if key == "metrics_hash_valid":
        return "Metrics artifact khớp episode set đang xem." if value else "Metrics artifact không khớp episode set; cần ưu tiên số tính lại từ episodes."
    if key == "metric_contract.benchmark_status":
        return f"Contract hiện ở trạng thái {value}; xem violations/null reasons để biết có reportable hay không."
    if key == "parse_errors":
        return "Dữ liệu đọc sạch, không phát hiện lỗi parse." if value == 0 else f"Có {value} lỗi parse; cần sửa file dữ liệu trước khi kết luận performance."
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        direction = _metric_direction(key)
        value_text = _metric_value_text(value, unit)
        sample = f" trên n={denominator}" if denominator not in (None, "", 0) else ""
        if key == "fdrc_validity_rate":
            # Validity is a precondition (episode đủ bằng chứng để chấm), not a quality
            # score. A run can hit 100% validity while the agent fails every episode, so
            # never phrase this as "tốt/ổn". Point the reader at the real pass metric.
            return (
                f"{label} đạt {value_text}{sample} — đây là CỔNG DỮ LIỆU (episode đủ bằng "
                "chứng để chấm), KHÔNG phải điểm chất lượng. Validity cao chỉ nghĩa là số "
                "liệu đáng tin; xem fdrc_pass_at_1 để biết agent làm tốt hay không."
            )
        if unit == "rate" and direction == "higher_is_better":
            if value >= 0.9:
                level = "tốt"
                action = "có thể xem là ổn nếu dữ liệu reportable."
            elif value >= 0.7:
                level = "trung bình"
                action = "nên xem các episode fail để tìm mẫu lỗi lặp lại."
            else:
                level = "yếu"
                action = "cần ưu tiên debug vì tỷ lệ đạt chưa đủ tin cậy cho trải nghiệm người dùng."
            return f"{label} đạt {value_text}{sample}, mức {level}; {action}"
        if unit == "rate" and direction == "lower_is_better":
            if value <= 0.05:
                level = "tốt"
                action = "rủi ro hiện thấp."
            elif value <= 0.2:
                level = "cần theo dõi"
                action = "nên kiểm tra nhóm episode gây lỗi."
            else:
                level = "xấu"
                action = "đây là rủi ro chính cần giảm trước khi báo cáo performance."
            return f"{label} là {value_text}{sample}, mức {level}; {action}"
        if unit == "ms":
            if value <= 700:
                return f"{label} là {value_text}, trong ngưỡng phản hồi chấp nhận được cho barge-in."
            return f"{label} là {value_text}, vượt ngưỡng 700 ms; người dùng có thể cảm thấy agent phản ứng chậm."
        if unit == "count":
            if value == 0 and (status in {"ok", None}):
                return f"{label} bằng 0; không thấy vấn đề ở chỉ số đếm này."
            return f"{label} hiện là {value_text}{sample}; cần đọc danh sách episode/evidence để xác định nguyên nhân."
    return f"Giá trị hiện tại của {label} là {_metric_value_text(value, unit)}; dùng cùng evidence để diễn giải trong ngữ cảnh run."


def _metric_plain_meaning(key: str, description: str) -> str:
    return METRIC_PLAIN_MEANINGS.get(key) or METRIC_PLAIN_MEANINGS.get(key.split(".", 1)[0]) or description


def _build_metric_catalog(
    metrics: dict[str, Any],
    *,
    selected_track: str | None,
    metric_source: str,
    metrics_hash_valid: bool,
    parse_errors: list[dict[str, Any]],
    latency_summary: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    contract = metrics.get("metric_contract") if isinstance(metrics.get("metric_contract"), dict) else {}
    denominators = contract.get("denominators", {}) if isinstance(contract, dict) else {}
    null_reasons = contract.get("null_reasons", {}) if isinstance(contract, dict) else {}
    nullable_metrics = contract.get("nullable_metrics", {}) if isinstance(contract, dict) else {}
    violations = {
        str(row.get("metric"))
        for row in (contract.get("violations", []) if isinstance(contract, dict) else [])
        if isinstance(row, dict) and row.get("metric")
    }
    flat_metrics = _flatten_metrics(metrics, latency_summary)
    flat_metrics["metrics_hash_valid"] = metrics_hash_valid
    flat_metrics["parse_errors"] = len(parse_errors)
    catalog = []
    for key in _catalog_keys(flat_metrics, selected_track):
        value = flat_metrics.get(key)
        label, description, unit, group = _metric_meta(key)
        base_key = key.split(".", 1)[0]
        nullable = key in nullable_metrics or base_key in nullable_metrics
        reason_payload = null_reasons.get(key) or null_reasons.get(base_key)
        null_reason = (
            reason_payload.get("null_reason")
            if isinstance(reason_payload, dict)
            else reason_payload
        )
        if value is None and not null_reason:
            null_reason = _synth_null_reason(key, metrics)
        denominator_payload = (
            denominators.get(key)
            if key in denominators
            else denominators.get(base_key)
        )
        status = _metric_status(key, value, nullable, violations)
        plain_meaning = _metric_plain_meaning(key, description)
        result_comment = _metric_result_comment(
            key,
            value,
            unit,
            denominator=denominator_payload,
            null_reason=null_reason,
            status=status,
        )
        catalog.append(
            {
                "key": key,
                "label": label,
                "description": description,
                "plain_meaning": plain_meaning,
                "result_comment": result_comment,
                "value": value,
                "unit": unit,
                "group": group,
                "track": selected_track,
                "source": metric_source,
                "denominator": denominator_payload,
                "nullable": nullable,
                "null_reason": null_reason,
                "status": status,
            }
        )
    present = {row["key"] for row in catalog}
    groups = []
    for group in METRIC_GROUPS:
        if not _metric_group_applies(group["id"], selected_track):
            continue
        keys = []
        for key in group["metric_keys"]:
            if key.endswith(".*"):
                keys.extend(sorted(item for item in present if item.startswith(key[:-1])))
            elif key in present:
                keys.append(key)
        if keys:
            groups.append({"id": group["id"], "label": group["label"], "metric_keys": keys})
    return catalog, groups


def _episode_row(episode: dict[str, Any]) -> dict[str, Any]:
    failures = [str(failure) for failure in (episode.get("failure_types", []) or [])]
    latency = episode.get("latency", {}) if isinstance(episode.get("latency"), dict) else {}
    scores = episode.get("scores", {}) if isinstance(episode.get("scores"), dict) else {}
    critical_slot_result = (
        episode.get("critical_slot_result")
        if isinstance(episode.get("critical_slot_result"), dict)
        else {}
    )
    repair = episode.get("repair") if isinstance(episode.get("repair"), dict) else {}
    validity = (
        episode.get("fdrc_validity")
        if isinstance(episode.get("fdrc_validity"), dict)
        else {}
    )
    tool_names = [
        str(call.get("tool"))
        for call in episode.get("tool_calls", []) or []
        if isinstance(call, dict) and call.get("tool")
    ]
    return {
        "episode_id": episode.get("episode_id"),
        "benchmark_track": episode.get("benchmark_track"),
        "domain": episode.get("domain"),
        "mode": episode.get("mode"),
        "base_task_id": episode.get("base_task_id"),
        "speech_overlay_id": episode.get("speech_overlay_id"),
        "model": episode.get("model"),
        "agent": episode.get("agent"),
        "accent_region": episode.get("accent_region"),
        "speech_speed": episode.get("speech_speed"),
        "audio_condition_id": episode.get("audio_condition_id"),
        "passed": _score_pass(episode),
        "primary_failure_type": episode.get("primary_failure_type"),
        "failure_types": failures,
        "tool_names": tool_names,
        "tool_call_count": len(episode.get("tool_calls", []) or []),
        "validation_error_count": len(episode.get("validation_errors", []) or []),
        "response_latency_ms": latency.get("response_latency_ms"),
        "yield_latency_ms": latency.get("yield_latency_ms"),
        "tool_exact_match": scores.get("tool_exact_match"),
        "argument_exact_match": scores.get("argument_exact_match"),
        "state_match": scores.get("state_match"),
        "critical_slot_passed": critical_slot_result.get("passed"),
        "critical_slot_correct": critical_slot_result.get("correct"),
        "critical_slot_total": critical_slot_result.get("total"),
        "correction_uptaken": repair.get("correction_uptaken"),
        "old_intent_committed": repair.get("old_intent_committed"),
        "forbidden_tool_called": repair.get("forbidden_tool_called"),
        "cancel_respected": repair.get("cancel_respected"),
        "cancel_attempted_tool_call": repair.get("cancel_attempted_tool_call"),
        "cancel_tool_call_count": repair.get("cancel_tool_call_count"),
        "cancel_blocked_tool_call_count": repair.get("cancel_blocked_tool_call_count"),
        "duplicate_final_commit": repair.get("duplicate_final_commit"),
        "tool_commit_time_ms": repair.get("tool_commit_time_ms"),
        "final_intent": repair.get("final_intent"),
        "fdrc_valid": validity.get("valid"),
        "fdrc_validity_status": validity.get("status"),
        "fdrc_invalid_reasons": validity.get("reasons", []),
    }


def _timeline(episode: dict[str, Any]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for event in episode.get("voice_events", []) or []:
        if isinstance(event, dict):
            events.append({**event, "source": event.get("source") or "voice"})
    events.extend(_assistant_response_events(episode.get("normalized_events", []) or []))
    for event in episode.get("normalized_events", []) or []:
        if not isinstance(event, dict):
            continue
        event_type = event.get("type") or event.get("event")
        if event_type == "tool_call":
            events.append(
                {
                    "event": "tool_call",
                    "t_ms": event.get("t_ms"),
                    "tool": event.get("tool"),
                    "args": event.get("args"),
                    "source": "normalized",
                }
            )
    for call in episode.get("tool_calls", []) or []:
        if isinstance(call, dict) and call.get("t_ms") is not None:
            events.append(
                {
                    "event": "tool_call",
                    "t_ms": call.get("t_ms"),
                    "tool": call.get("tool"),
                    "args": call.get("args"),
                    "source": "tool_calls",
                }
            )
    sorted_events = sorted(
        (_enrich_timeline_event(event) for event in _dedupe_timeline_events(events)),
        key=lambda event: event["t_ms"],
    )
    return [
        {**event, "priority": event.get("event") in PRIORITY_TIMELINE_EVENTS}
        for event in sorted_events
    ]


EXPECTED_TIMELINE_MARKERS = {
    "assistant_speech_expected_start",
    "assistant_should_yield_by",
    "tool_commit_allowed_after",
}

USER_TIMELINE_EVENTS = {
    "user_speech_start",
    "user_interrupt_start",
    "repair_audio_start",
}

ASSISTANT_TIMELINE_EVENTS = {
    "assistant_speech_start",
    "assistant_speech_stop",
    "assistant_yielded",
    "assistant_response",
}

TOOL_TIMELINE_EVENTS = {"tool_call", "tool_result"}

ASR_TIMELINE_EVENTS = {"repair_transcript_done"}


def _timeline_sources(event: dict[str, Any]) -> list[str]:
    sources = event.get("sources")
    if isinstance(sources, list) and sources:
        return [str(source) for source in sources if source not in (None, "")]
    source = event.get("source")
    return [str(source)] if source not in (None, "") else []


def _timeline_lane(event_name: str, sources: list[str]) -> str:
    if "expected" in sources or event_name in EXPECTED_TIMELINE_MARKERS:
        return "marker"
    if event_name in USER_TIMELINE_EVENTS:
        return "user"
    if event_name in ASSISTANT_TIMELINE_EVENTS:
        return "assistant"
    if event_name in TOOL_TIMELINE_EVENTS:
        return "tool"
    if event_name == "final_state":
        return "system"
    if "expected" in sources:
        return "marker"
    return "system"


def _timeline_kind(event_name: str, sources: list[str]) -> str:
    if "expected" in sources or event_name in EXPECTED_TIMELINE_MARKERS:
        return "marker"
    if event_name == "assistant_response":
        return "derived"
    if event_name == "tool_call" and sources and all(
        source == "normalized" for source in sources
    ):
        return "derived"
    if "normalized" in sources and not (
        "observed" in sources or "tool_calls" in sources
    ):
        return "derived"
    return "runtime"


def _timeline_timestamp_kind(event_name: str, kind: str, sources: list[str]) -> str:
    if kind == "marker" or "expected" in sources:
        return "scheduled"
    if event_name in {"user_speech_start", "user_interrupt_start", "repair_audio_start", "assistant_speech_start"}:
        return "audio_onset"
    if event_name in ASR_TIMELINE_EVENTS:
        return "asr_done"
    if kind == "derived":
        return "normalized"
    return "runtime_observed"


def _enrich_timeline_event(event: dict[str, Any]) -> dict[str, Any]:
    event_name = str(event.get("event") or "")
    sources = _timeline_sources(event)
    lane = event.get("lane") or _timeline_lane(event_name, sources)
    kind = event.get("kind") or _timeline_kind(event_name, sources)
    timestamp_kind = event.get("timestamp_kind") or _timeline_timestamp_kind(
        event_name, kind, sources
    )
    source = event.get("source")
    if source in (None, "") and sources:
        source = sources[0]
    return {
        **event,
        "source": source,
        "sources": sources,
        "kind": kind,
        "lane": lane,
        "timestamp_kind": timestamp_kind,
    }


def _timeline_key(event: dict[str, Any]) -> tuple[Any, ...]:
    args = event.get("args")
    try:
        args_key = json.dumps(args, ensure_ascii=False, sort_keys=True)
    except TypeError:
        args_key = str(args)
    return (
        event.get("event"),
        event.get("t_ms"),
        event.get("tool"),
        args_key,
        event.get("text"),
    )


def _dedupe_timeline_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[tuple[Any, ...], dict[str, Any]] = {}
    for event in events:
        if not isinstance(event.get("t_ms"), (int, float)):
            continue
        key = _timeline_key(event)
        source = event.get("source")
        if key not in merged:
            merged[key] = dict(event)
            continue
        row = merged[key]
        sources = row.setdefault("sources", [])
        existing_source = row.get("source")
        if existing_source and str(existing_source) not in sources:
            sources.append(str(existing_source))
        if source and str(source) not in sources:
            sources.append(str(source))
        if not row.get("source") and source:
            row["source"] = source
    return list(merged.values())


def _assistant_response_events(normalized_events: list[Any]) -> list[dict[str, Any]]:
    response_events: list[dict[str, Any]] = []
    active: dict[str, Any] | None = None

    def flush() -> None:
        nonlocal active
        if active is None:
            return
        text = "".join(active["parts"]).strip()
        if text:
            response_events.append(
                {
                    "event": "assistant_response",
                    "t_ms": active["t_ms"],
                    "text": text,
                    "delta_count": len(active["parts"]),
                    "source": "normalized",
                }
            )
        active = None

    for event in normalized_events:
        if not isinstance(event, dict):
            continue
        event_type = event.get("type") or event.get("event")
        if event_type in {"assistant_text_delta", "assistant_transcript_delta"}:
            text = event.get("text")
            t_ms = event.get("t_ms")
            if not text or not isinstance(t_ms, (int, float)):
                continue
            if active is None:
                active = {"t_ms": t_ms, "parts": []}
            active["parts"].append(str(text))
        elif event_type in {
            "assistant_speech_stop",
            "assistant_yielded",
            "tool_call",
            "tool_result",
            "response.done",
        }:
            flush()
    flush()
    return response_events


def _metadata(episodes: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "tracks": _values(episodes, "benchmark_track"),
        "domains": _values(episodes, "domain"),
        "providers": _values(episodes, "provider"),
        "models": _values(episodes, "model"),
        "adapters": _values(episodes, "adapter"),
        "modes": _values(episodes, "mode"),
        "agents": _values(episodes, "agent"),
        "accent_regions": _values(episodes, "accent_region"),
        "speech_speeds": _values(episodes, "speech_speed"),
        "audio_conditions": _values(episodes, "audio_condition_id"),
    }


def _benchmark_command_base(script: str) -> list[str]:
    stem = Path(script).stem
    module_path = ROOT_DIR / "src" / f"{stem}.py"
    if module_path.exists():
        return [sys.executable, "-m", f"src.{stem}"]
    return [sys.executable, str(ROOT_DIR / script)]


class DashboardStore:
    def __init__(self, results_dir: Path) -> None:
        self.results_dir = results_dir if results_dir.is_absolute() else ROOT_DIR / results_dir

    def _run_path(self, run_id: str) -> Path:
        path = self.results_dir / run_id
        try:
            path.resolve().relative_to(self.results_dir.resolve())
        except ValueError as exc:
            raise RunNotFound(run_id) from exc
        if not path.is_dir():
            raise RunNotFound(run_id)
        return path

    def _load_run(
        self, run_id: str
    ) -> tuple[Path, dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
        path = self._run_path(run_id)
        metrics_path = path / "metrics.json"
        episodes_path = path / "episodes.jsonl"
        metrics: dict[str, Any] = {}
        errors: list[dict[str, Any]] = []
        if metrics_path.exists():
            loaded_metrics, metric_errors = _read_json(metrics_path)
            errors.extend(metric_errors)
            if isinstance(loaded_metrics, dict):
                metrics = loaded_metrics
        episodes: list[dict[str, Any]] = []
        if episodes_path.exists():
            episodes, episode_errors = _read_jsonl(episodes_path)
            errors.extend(episode_errors)
        return path, metrics, episodes, errors

    def list_runs(self) -> list[dict[str, Any]]:
        if not self.results_dir.exists():
            return []
        runs = []
        for path in sorted(self.results_dir.iterdir(), key=lambda item: item.name):
            if not path.is_dir():
                continue
            metrics_path = path / "metrics.json"
            episodes_path = path / "episodes.jsonl"
            if not metrics_path.exists() and not episodes_path.exists():
                continue
            _, metrics, episodes, errors = self._load_run(path.name)
            metadata = _metadata(episodes)
            track = _dominant_track(episodes)
            kind = _run_kind(path.name)
            provenance = _data_provenance(path.name, episodes)
            runs.append(
                {
                    "run_id": path.name,
                    "episode_count": len(episodes),
                    "has_metrics": bool(metrics),
                    "has_episodes": episodes_path.exists(),
                    "status": "partial" if errors or not metrics or not episodes else "complete",
                    "updated_at": _mtime_iso([metrics_path, episodes_path]),
                    "benchmark_track": track,
                    "benchmark_label": _track_label(track),
                    "run_kind": kind,
                    "data_provenance": provenance,
                    "provenance_label": _provenance_label(provenance),
                    "provenance_warning": _provenance_warning(provenance),
                    "primary": provenance == "provider"
                    and track in {POLICY_TRACK, FDRC_TRACK},
                    **metadata,
                }
            )
        return sorted(runs, key=lambda row: row.get("updated_at") or "", reverse=True)

    def _scoped_evaluation_episodes(
        self, run_id: str, track: str | None = None
    ) -> tuple[list[dict[str, Any]], str | None, str, bool, dict[str, Any]]:
        path, metrics, raw_episodes, _errors = self._load_run(run_id)
        selected_track = track or _dominant_track(raw_episodes)
        raw_scoped = [
            e for e in raw_episodes
            if not selected_track or e.get("benchmark_track") == selected_track
        ]
        episodes = _evaluation_view(raw_episodes)
        scoped = [
            e for e in episodes
            if not selected_track or e.get("benchmark_track") == selected_track
        ]
        metrics_valid = bool(metrics) and metrics.get("episode_set_hash") == episode_set_hash(raw_scoped)
        metric_source = "metrics.json" if metrics_valid else "episodes.jsonl"
        return scoped, selected_track, metric_source, metrics_valid, (metrics or {})

    def run_summary(
        self,
        run_id: str,
        track: str | None = None,
        domain: str | None = None,
        audio_condition_id: str | None = None,
        difficulty: str | None = None,
    ) -> dict[str, Any]:
        path, metrics, raw_episodes, errors = self._load_run(run_id)
        selected_track = track or _dominant_track(raw_episodes)
        selected_audio_condition = _audio_condition_for_difficulty(
            audio_condition_id, difficulty
        )
        raw_scoped_episodes = [
            episode
            for episode in raw_episodes
            if not selected_track or episode.get("benchmark_track") == selected_track
        ]
        episodes = _evaluation_view(raw_episodes)
        scoped_episodes = [
            episode
            for episode in episodes
            if not selected_track or episode.get("benchmark_track") == selected_track
        ]
        # Per-domain slice (Compare tab): narrow both the scored and the raw
        # episode sets so derived metrics recompute from just that domain. The
        # raw-set filter also breaks the metrics.json hash match, so the
        # whole-run metrics.json is (correctly) NOT used for a domain slice.
        if domain:
            scoped_episodes = [e for e in scoped_episodes if e.get("domain") == domain]
            raw_scoped_episodes = [
                e for e in raw_scoped_episodes if e.get("domain") == domain
            ]
        if selected_audio_condition:
            scoped_episodes = [
                e
                for e in scoped_episodes
                if e.get("audio_condition_id") == selected_audio_condition
            ]
            raw_scoped_episodes = [
                e
                for e in raw_scoped_episodes
                if e.get("audio_condition_id") == selected_audio_condition
            ]
        derived_metrics = _summarize_from_episodes(scoped_episodes, selected_track)
        expected_hash = episode_set_hash(raw_scoped_episodes)
        metrics_hash = metrics.get("episode_set_hash")
        metrics_valid = bool(metrics) and metrics_hash == expected_hash
        metric_errors = []
        if metrics and not metrics_valid:
            metric_errors.append(
                {
                    "file": str(path / "metrics.json"),
                    "line": None,
                    "error": "metrics_hash_mismatch_or_missing",
                }
            )
        errors = [*errors, *metric_errors]
        display_metrics = {**(metrics or {}), **derived_metrics} if metrics_valid else derived_metrics
        metric_source = "episodes.jsonl"
        contract_status = (
            display_metrics.get("metric_contract", {}).get("benchmark_status")
            if isinstance(display_metrics.get("metric_contract"), dict)
            else None
        )
        summary_status = contract_status or (
            "partial" if errors or not metrics or not episodes else "complete"
        )
        passed = sum(1 for episode in scoped_episodes if _score_pass(episode) is True)
        failed = sum(1 for episode in scoped_episodes if _score_pass(episode) is False)
        unscored = len(scoped_episodes) - passed - failed
        provenance = _data_provenance(path.name, episodes)
        latency_distribution = _latency_distribution(scoped_episodes)
        latency_summary = _latency_summary(scoped_episodes)
        top_yield_latency = _top_latency_episodes(scoped_episodes, "yield_latency_ms")
        top_response_latency = _top_latency_episodes(scoped_episodes, "response_latency_ms")
        metric_catalog, metric_groups = _build_metric_catalog(
            display_metrics,
            selected_track=selected_track,
            metric_source=metric_source,
            metrics_hash_valid=metrics_valid,
            parse_errors=errors,
            latency_summary=latency_summary,
        )
        metric_contract = (
            display_metrics.get("metric_contract")
            if isinstance(display_metrics.get("metric_contract"), dict)
            else {}
        )
        return {
            "run_id": path.name,
            "status": summary_status,
            "updated_at": _mtime_iso([path / "metrics.json", path / "episodes.jsonl"]),
            "benchmark_track": selected_track,
            "benchmark_label": _track_label(selected_track),
            "run_kind": _run_kind(path.name),
            "data_provenance": provenance,
            "provenance_label": _provenance_label(provenance),
            "provenance_warning": _provenance_warning(provenance),
            "metrics": display_metrics,
            "derived_metrics": derived_metrics,
            "metric_catalog": metric_catalog,
            "metric_groups": metric_groups,
            "metric_contract": metric_contract,
            "null_reasons": metric_contract.get("null_reasons", {}),
            "denominators": metric_contract.get("denominators", {}),
            "decision_confusion_matrix": display_metrics.get("decision_confusion_matrix", []),
            "state_pairs": display_metrics.get("state_pairs", []),
            "metric_source": metric_source,
            "metrics_hash_valid": metrics_valid,
            "episode_count": len(scoped_episodes),
            "parse_errors": errors,
            "metadata": _metadata(scoped_episodes),
            "run_metadata": (
                metrics.get("run_metadata")
                if isinstance(metrics.get("run_metadata"), dict)
                else {}
            ),
            "pass_fail": {"passed": passed, "failed": failed, "unscored": unscored},
            "pass_by_domain": _group_pass_rate(scoped_episodes, "domain"),
            "pass_by_mode": _group_pass_rate(scoped_episodes, "mode"),
            "pass_by_track": _group_pass_rate(scoped_episodes, "benchmark_track"),
            "pass_by_accent_region": _group_pass_rate(scoped_episodes, "accent_region"),
            "pass_by_speech_speed": _group_pass_rate(scoped_episodes, "speech_speed"),
            "pass_by_audio_condition": _group_pass_rate(scoped_episodes, "audio_condition_id"),
            "primary_failure_counts": _failure_counts(scoped_episodes, primary=True),
            "failure_counts": _failure_counts(scoped_episodes),
            "latency_distribution": latency_distribution,
            "latency_summary": latency_summary,
            "top_yield_latency_episodes": top_yield_latency,
            "top_response_latency_episodes": top_response_latency,
        }

    def explain_metric(
        self, run_id: str, metric_key: str, track: str | None = None
    ) -> dict[str, Any]:
        scoped, selected_track, metric_source, metrics_valid, metrics = self._scoped_evaluation_episodes(
            run_id, track
        )
        label, description, unit, group = _metric_meta(metric_key)
        plain_meaning = _metric_plain_meaning(metric_key, description)
        explain_fn = (
            explain_policy_gating_metric
            if selected_track == POLICY_TRACK
            else explain_fdrc_metric
        )
        explanation = explain_fn(metric_key, scoped) or {
            "key": metric_key,
            "supported": False,
        }
        base = {
            "run_id": run_id,
            "key": metric_key,
            "label": label,
            "description": description,
            "plain_meaning": plain_meaning,
            "unit": unit,
            "group": group,
            "benchmark_track": selected_track,
            "metric_source": metric_source,
            "metrics_hash_valid": metrics_valid,
        }
        if not explanation.get("supported"):
            base["supported"] = False
            base["note_vi"] = "Metric không hỗ trợ phân tích theo episode."
            return base
        by_id = {str(e.get("episode_id")): e for e in scoped}
        numerator_episodes = []
        for episode_id in explanation.get("numerator_episode_ids", []):
            episode = by_id.get(episode_id, {})
            numerator_episodes.append(
                {
                    "episode_id": episode_id,
                    "base_task_id": episode.get("base_task_id"),
                    "domain": episode.get("domain"),
                    "accent_region": episode.get("accent_region"),
                    "speech_speed": episode.get("speech_speed"),
                    "passed": _score_pass(episode),
                    "fdrc_valid": bool(episode.get("fdrc_validity", {}).get("valid")),
                }
            )
        denominator_episode_ids = [
            str(episode_id)
            for episode_id in explanation.get("denominator_episode_ids", [])
        ]
        numerator_id_set = {
            str(episode_id)
            for episode_id in explanation.get("numerator_episode_ids", [])
        }
        if metric_key in METRIC_NUMERATOR_IS_FAILURE:
            failed_episode_ids = [
                episode_id for episode_id in denominator_episode_ids if episode_id in numerator_id_set
            ]
            successful_episode_ids = [
                episode_id for episode_id in denominator_episode_ids if episode_id not in numerator_id_set
            ]
        else:
            successful_episode_ids = [
                episode_id for episode_id in denominator_episode_ids if episode_id in numerator_id_set
            ]
            failed_episode_ids = [
                episode_id for episode_id in denominator_episode_ids if episode_id not in numerator_id_set
            ]
        evidence_rows = _explain_evidence_rows(
            metric_key,
            selected_track,
            explanation,
            by_id,
        )
        recomputed = explanation["value"]
        displayed = recomputed
        metric_json_value = metrics.get(metric_key) if metrics_valid and metric_key in metrics else None
        if metric_json_value is None and recomputed is None:
            metrics_matches_recomputed = True
        elif isinstance(metric_json_value, (int, float)) and isinstance(recomputed, (int, float)):
            metrics_matches_recomputed = abs(metric_json_value - recomputed) < 1e-9
        elif metric_json_value is None and metric_key not in metrics:
            metrics_matches_recomputed = True
        else:
            metrics_matches_recomputed = metric_json_value == recomputed
        base.update(
            {
                "supported": True,
                "metric_source": "episodes.jsonl",
                "result_comment": _metric_result_comment(
                    metric_key,
                    displayed,
                    unit,
                    denominator=explanation.get("denominator"),
                ),
                "scope": explanation["scope"],
                "formula_vi": explanation["formula_vi"],
                "row_set_label_vi": explanation["row_set_label_vi"],
                "numerator_label_vi": explanation["numerator_label_vi"],
                "numerator": explanation["numerator"],
                "denominator": explanation["denominator"],
                "value": displayed,
                "recomputed_value": recomputed,
                "value_matches_recomputed": True,
                "metrics_json_value": metric_json_value,
                "metrics_json_matches_recomputed": metrics_matches_recomputed,
                "numerator_episodes": numerator_episodes,
                "denominator_episode_count": len(denominator_episode_ids),
                "denominator_episodes": evidence_rows,
                "successful_episode_count": len(successful_episode_ids),
                "failed_episode_count": len(failed_episode_ids),
                "successful_episodes": _explain_sample_rows(
                    metric_key,
                    selected_track,
                    successful_episode_ids,
                    by_id,
                ),
                "failed_episodes": _explain_sample_rows(
                    metric_key,
                    selected_track,
                    failed_episode_ids,
                    by_id,
                ),
                "episode_sample_limit": METRIC_SAMPLE_LIMIT,
                "numerator_is_failure": metric_key in METRIC_NUMERATOR_IS_FAILURE,
                "denominator_condition_vi": explanation.get("denominator_condition_vi"),
                "pass_condition_vi": explanation.get("pass_condition_vi"),
                "evaluation_checks": explanation.get("evaluation_checks_vi", []),
                "calculation_vi": explanation.get("calculation_vi"),
                "explorer_filter": explanation["explorer_filter"],
            }
        )
        return base

    def list_episodes(
        self,
        run_id: str,
        *,
        track: str | None = None,
        domain: str | None = None,
        audio_condition_id: str | None = None,
        difficulty: str | None = None,
        mode: str | None = None,
        failure: str | None = None,
        passed: bool | None = None,
        validity: str | None = None,
    ) -> dict[str, Any]:
        _, _, episodes, errors = self._load_run(run_id)
        episodes = _evaluation_view(episodes)
        selected_audio_condition = _audio_condition_for_difficulty(
            audio_condition_id, difficulty
        )
        filtered = episodes
        if track:
            filtered = [episode for episode in filtered if episode.get("benchmark_track") == track]
        if domain:
            filtered = [episode for episode in filtered if episode.get("domain") == domain]
        if selected_audio_condition:
            filtered = [
                episode
                for episode in filtered
                if episode.get("audio_condition_id") == selected_audio_condition
            ]
        if mode:
            filtered = [episode for episode in filtered if episode.get("mode") == mode]
        if failure:
            filtered = [
                episode
                for episode in filtered
                if failure in (episode.get("failure_types") or [])
                or episode.get("primary_failure_type") == failure
            ]
        if validity:
            wanted = validity.casefold()
            filtered = [
                episode
                for episode in filtered
                if (
                    (
                        wanted == "valid"
                        and episode.get("fdrc_validity", {}).get("valid") is True
                    )
                    or (
                        wanted == "invalid"
                        and episode.get("fdrc_validity", {}).get("valid") is False
                    )
                )
            ]
        if passed is not None:
            filtered = [episode for episode in filtered if _score_pass(episode) is passed]
        return {
            "run_id": run_id,
            "total": len(episodes),
            "count": len(filtered),
            "parse_errors": errors,
            "episodes": [_episode_row(episode) for episode in filtered],
        }

    def episode_detail(self, run_id: str, episode_id: str) -> dict[str, Any] | None:
        _, _, episodes, errors = self._load_run(run_id)
        tasks = load_base_tasks()
        overlays = {row["speech_overlay_id"]: row for row in load_overlays()}
        episodes = _evaluation_view(episodes)
        for episode in episodes:
            if str(episode.get("episode_id")) == episode_id:
                overlay = overlays.get(episode.get("speech_overlay_id"), {})
                task = tasks.get(episode.get("base_task_id"), {})
                expected_tool_calls = overlay.get(
                    "expected_tool_calls", task.get("expected_tool_calls", [])
                )
                expected_final_state = overlay.get(
                    "expected_final_state", task.get("expected_final_state", {})
                )
                return {
                    "run_id": run_id,
                    "parse_errors": errors,
                    "summary": _episode_row(episode),
                    "contract": {
                        "base_task_id": episode.get("base_task_id"),
                        "speech_overlay_id": episode.get("speech_overlay_id"),
                        "task_description": task.get("description"),
                        "initial_spoken_utterance": overlay.get("initial_spoken_utterance")
                        or overlay.get("spoken_utterance"),
                        "repair_utterance": overlay.get("repair_utterance"),
                        "initial_intent": overlay.get("initial_intent"),
                        "final_intent": overlay.get("final_intent"),
                        "expected_tool_calls": expected_tool_calls,
                        "forbidden_tool_calls": overlay.get("forbidden_tool_calls", []),
                        "expected_final_state": expected_final_state,
                        "voice_timeline": overlay.get("voice_timeline", []),
                        "voice_assertions": overlay.get("voice_assertions", {}),
                    },
                    "slot_eval": {
                        "captured_slots": episode.get("captured_slots", {}),
                        "critical_slot_result": episode.get("critical_slot_result"),
                        "tool_exact_match": episode.get("scores", {}).get("tool_exact_match"),
                        "argument_exact_match": episode.get("scores", {}).get(
                            "argument_exact_match"
                        ),
                        "state_match": episode.get("scores", {}).get("state_match"),
                    },
                    "repair": episode.get("repair"),
                    "fdrc_validity": episode.get("fdrc_validity"),
                    "transcript": {
                        "user": episode.get("user_transcript", []),
                        "assistant": episode.get("assistant_transcript", []),
                    },
                    "tool_calls": episode.get("tool_calls", []),
                    "tool_results": episode.get("tool_results", []),
                    "validation_errors": episode.get("validation_errors", []),
                    "policy_violations": episode.get("policy_violations", []),
                    "initial_state": episode.get("initial_state", {}),
                    "final_state": episode.get("final_state", {}),
                    "state_diff": episode.get("state_diff"),
                    "scores": episode.get("scores", {}),
                    "failure_types": episode.get("failure_types", []),
                    "timeline": _timeline(episode),
                    "raw": episode,
                }
        return None

    def run_presets(self) -> list[dict[str, Any]]:
        return [
            {"id": key, **value}
            for key, value in RUN_PRESETS.items()
        ]

    def dashboard_config(self) -> dict[str, Any]:
        tasks = load_base_tasks()
        overlays = load_overlays()
        domains = sorted({task["domain"] for task in tasks.values()})
        overlay_counts: dict[str, dict[str, int]] = {
            POLICY_TRACK: {},
            FDRC_TRACK: {},
        }
        for overlay in overlays:
            track = overlay.get("benchmark_track")
            domain = overlay.get("domain")
            if track in overlay_counts and isinstance(domain, str):
                overlay_counts[track][domain] = overlay_counts[track].get(domain, 0) + 1
        personas = []
        for path in sorted((ROOT_DIR / "src" / "personas").glob("*.yaml")):
            fields = _read_top_level_yaml_fields(path)
            persona_id = fields.get("persona_id", path.stem)
            accent = fields.get("accent_region", persona_id.split("_")[1] if "_" in persona_id else "")
            speed = fields.get("speech_speed", persona_id.rsplit("_", 1)[-1])
            label = fields.get("accent_region_label", accent)
            personas.append(
                {
                    "persona_id": persona_id,
                    "accent_region": accent,
                    "accent_region_label": label,
                    "speech_speed": speed,
                    "speech_speed_label": SPEED_LABELS.get(speed, speed),
                }
            )
        audio_conditions = []
        for path in sorted((ROOT_DIR / "src" / "audio_conditions").glob("*.yaml")):
            fields = _read_top_level_yaml_fields(path)
            condition_id = fields.get("condition_id", path.stem)
            audio_conditions.append(
                {
                    "condition_id": condition_id,
                    "description": fields.get("description", condition_id),
                    "barge_in_enabled": fields.get("barge_in_enabled"),
                }
            )
        return {
            "tracks": {
                POLICY_TRACK: {
                    "label": BENCHMARK_LABELS[POLICY_TRACK],
                    "description": TRACK_DESCRIPTIONS[POLICY_TRACK],
                },
                FDRC_TRACK: {
                    "label": BENCHMARK_LABELS[FDRC_TRACK],
                    "description": TRACK_DESCRIPTIONS[FDRC_TRACK],
                },
            },
            "domains": [
                {"domain": domain, "label": DOMAIN_LABELS.get(domain, domain)}
                for domain in domains
            ],
            "personas": personas,
            "speech_speeds": [
                {"speech_speed": key, "label": value}
                for key, value in SPEED_LABELS.items()
            ],
            "audio_conditions": audio_conditions,
            "overlay_counts": overlay_counts,
            "policy_gating_audio_modes": ["clean"],
            "fdrc_audio_modes": FDRC_COMPARE_AUDIO_CONDITIONS,
            "fdrc_difficulties": FDRC_DIFFICULTIES,
        }

    def start_benchmark_run(
        self,
        preset_id: str,
        *,
        domains: str = "automotive,navigation,media_phone",
        personas: str = "vi_north_normal,vi_central_normal,vi_south_normal",
        audio_conditions: str | None = None,
        model: str | None = None,
    ) -> dict[str, Any]:
        preset = RUN_PRESETS.get(preset_id)
        if preset is None:
            raise ValueError(f"Unknown run preset: {preset_id}")
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output = self.results_dir / f"{preset['default_output_prefix']}_{stamp}"
        command = [
            *_benchmark_command_base(preset["script"]),
            *preset["args"],
            "--domains",
            domains,
            "--personas",
            personas,
            "--output",
            str(output),
        ]
        if preset["benchmark_track"] == FDRC_TRACK:
            command.extend(["--fdrc-yield-mode", "native_yield"])
            command.extend(
                [
                    "--audio-conditions",
                    audio_conditions or ",".join(FDRC_COMPARE_AUDIO_CONDITIONS),
                ]
            )
        if model:
            command.extend(["--model", model])
        job_id = str(uuid.uuid4())
        process = subprocess.Popen(
            command,
            cwd=ROOT_DIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        RUN_JOBS[job_id] = {
            "job_id": job_id,
            "preset_id": preset_id,
            "label": preset["label"],
            "benchmark_track": preset["benchmark_track"],
            "command": command,
            "output": str(output),
            "run_id": output.name,
            "pid": process.pid,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "process": process,
        }
        return self.job_status(job_id)

    def job_status(self, job_id: str) -> dict[str, Any]:
        job = RUN_JOBS.get(job_id)
        if job is None:
            raise RunNotFound(job_id)
        process: subprocess.Popen[str] = job["process"]
        return_code = process.poll()
        status = "running" if return_code is None else "succeeded" if return_code == 0 else "failed"
        stdout = ""
        stderr = ""
        if return_code is not None and "completed" not in job:
            stdout, stderr = process.communicate()
            job["stdout"] = stdout[-4000:]
            job["stderr"] = stderr[-4000:]
            job["completed"] = True
            job["completed_at"] = datetime.now(timezone.utc).isoformat()
        return {
            key: value
            for key, value in job.items()
            if key not in {"process"}
        } | {
            "status": status,
            "return_code": return_code,
            "stdout": job.get("stdout", ""),
            "stderr": job.get("stderr", ""),
        }
