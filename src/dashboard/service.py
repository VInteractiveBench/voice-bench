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
from src.evaluator.retention_evaluator import evaluate_retention_episode, summarize_retention
from src.runner import episode_set_hash


ROOT_DIR = Path(__file__).resolve().parents[2]
RETENTION_TRACK = "text_to_voice_retention"
FDRC_TRACK = "full_duplex_repair_to_commit"
PRIORITY_TIMELINE_EVENTS = {
    "assistant_speech_start",
    "user_interrupt_start",
    "assistant_yielded",
    "assistant_should_yield_by",
    "tool_commit_allowed_after",
    "tool_call",
}

RUN_JOBS: dict[str, dict[str, Any]] = {}

BENCHMARK_LABELS = {
    RETENTION_TRACK: "Text-to-Voice Capability Retention",
    FDRC_TRACK: "Full-Duplex Repair-to-Commit",
}

RUN_PRESETS = {
    "retention_reference": {
        "label": "Retention reference-agent",
        "benchmark_track": RETENTION_TRACK,
        "script": "run_voice_retention.py",
        "args": ["--reference-agent"],
        "default_output_prefix": "dashboard_retention_reference",
    },
    "retention_openai": {
        "label": "Retention OpenAI realtime",
        "benchmark_track": RETENTION_TRACK,
        "script": "run_voice_retention.py",
        "args": ["--agent", "openai_realtime"],
        "default_output_prefix": "dashboard_retention_openai",
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
    RETENTION_TRACK: (
        "Đo mức Vivi giữ được năng lực từ text baseline sang voice, đặc biệt "
        "critical slots, tool calls, arguments và final state."
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
        "id": "retention",
        "label": "Text-to-Voice Retention",
        "metric_keys": [
            "text_pass_at_1",
            "clean_voice_pass_at_1",
            "cabin_voice_pass_at_1",
            "clean_voice_retention",
            "voice_capability_retention",
            "voice_degradation_gap",
            "critical_slot_accuracy",
            "complete_pair_count",
            "incomplete_pair_count",
            "accent_gap",
            "speed_gap",
        ],
    },
    {
        "id": "retention_degradation",
        "label": "Retention Degradation",
        "metric_keys": ["degradation_by_component.*"],
    },
    {
        "id": "fdrc",
        "label": "Full-Duplex Repair-to-Commit",
        "metric_keys": [
            "performance_fdrc_pass_at_1",
            "fdrc_validity_rate",
            "raw_fdrc_pass_at_1",
            "fdrc_pass_at_1",
            "valid_episode_count",
            "invalid_episode_count",
            "validity_failure_counts",
            "correction_uptake_rate",
            "old_intent_suppression_rate",
            "forbidden_tool_call_rate",
            "cancel_success_rate",
            "yield_latency_pass_rate",
        ],
    },
    {
        "id": "latency",
        "label": "Latency",
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
    "text_pass_at_1": ("Pass text baseline", "Tỷ lệ pass của các episode text baseline.", "rate", "retention"),
    "clean_voice_pass_at_1": ("Pass voice sạch", "Tỷ lệ pass khi input là giọng nói sạch.", "rate", "retention"),
    "cabin_voice_pass_at_1": ("Pass voice cabin", "Tỷ lệ pass khi input là giọng nói có nhiễu cabin.", "rate", "retention"),
    "clean_voice_retention": ("Giữ năng lực voice sạch", "clean_voice_pass_at_1 / text_pass_at_1.", "rate", "retention"),
    "voice_capability_retention": ("Giữ năng lực voice cabin", "cabin_voice_pass_at_1 / text_pass_at_1.", "rate", "retention"),
    "voice_degradation_gap": ("Khoảng suy giảm voice", "text_pass_at_1 - cabin_voice_pass_at_1.", "rate", "retention"),
    "critical_slot_accuracy": ("Đúng critical slot", "Tỷ lệ slot quan trọng được giữ đúng.", "rate", "retention"),
    "complete_pair_count": ("Cặp retention đủ", "Số cặp task có đủ text, clean voice và cabin voice.", "count", "retention"),
    "incomplete_pair_count": ("Cặp retention thiếu", "Số cặp task thiếu ít nhất một mode retention.", "count", "retention"),
    "accent_gap": ("Chênh lệch vùng giọng", "Khoảng cách pass rate lớn nhất giữa các accent region.", "rate", "retention"),
    "speed_gap": ("Chênh lệch tốc độ nói", "Khoảng cách pass rate lớn nhất giữa các speech speed.", "rate", "retention"),
    "fdrc_pass_at_1": ("Pass FDRC", "Tỷ lệ episode FDRC pass toàn bộ tiêu chí.", "rate", "fdrc"),
    "performance_fdrc_pass_at_1": ("Pass FDRC performance", "Pass rate chỉ tính trên episode FDRC hợp lệ.", "rate", "fdrc"),
    "raw_fdrc_pass_at_1": ("Pass FDRC raw", "Pass rate trên toàn bộ episode, giữ để forensic.", "rate", "fdrc"),
    "fdrc_validity_rate": ("Validity FDRC", "Tỷ lệ episode có đủ evidence để chấm performance.", "rate", "fdrc"),
    "valid_episode_count": ("Episode hợp lệ", "Số episode FDRC đủ evidence để tính performance.", "count", "fdrc"),
    "invalid_episode_count": ("Episode invalid", "Số episode FDRC thiếu evidence hoặc transcript/tool/state hợp lệ.", "count", "fdrc"),
    "validity_failure_counts": ("Lý do invalid", "Danh sách lý do khiến episode không đủ điều kiện performance.", "count", "fdrc"),
    "correction_uptake_rate": ("Tiếp nhận sửa", "Tỷ lệ episode tiếp nhận đúng final repair intent.", "rate", "fdrc"),
    "old_intent_suppression_rate": ("Chặn ý định cũ", "Tỷ lệ episode không commit ý định cũ.", "rate", "fdrc"),
    "forbidden_tool_call_rate": ("Gọi tool bị cấm", "Tỷ lệ episode có forbidden tool call.", "rate", "fdrc"),
    "cancel_success_rate": ("Cancel thành công", "Tỷ lệ cancel case không tạo side effect bị cấm.", "rate", "fdrc"),
    "yield_latency_pass_rate": ("Pass latency", "Tỷ lệ episode có yield latency trong ngưỡng cho phép.", "rate", "fdrc"),
    "yield_latency_p50_ms": ("P50 nhường lời", "Trung vị độ trễ nhường lời sau khi user chen ngang.", "ms", "latency"),
    "yield_latency_p95_ms": ("P95 nhường lời", "Phân vị 95 của độ trễ nhường lời.", "ms", "latency"),
    "performance_yield_latency_p50_ms": ("P50 yield performance", "P50 yield latency chỉ trên episode hợp lệ.", "ms", "latency"),
    "performance_yield_latency_p95_ms": ("P95 yield performance", "P95 yield latency chỉ trên episode hợp lệ.", "ms", "latency"),
    "performance_yield_latency_pass_rate": ("Yield pass performance", "Yield pass rate chỉ trên episode hợp lệ.", "rate", "latency"),
    "metric_contract.benchmark_status": ("Trạng thái contract", "Trạng thái hợp lệ của metric contract.", "text", "contract"),
    "metric_contract.violations": ("Vi phạm contract", "Số metric bắt buộc bị thiếu hoặc không hợp lệ.", "count", "contract"),
    "metric_contract.null_reasons": ("Metric nullable rỗng", "Số metric nullable đang không có mẫu hợp lệ.", "count", "contract"),
    "metrics_hash_valid": ("Hash metrics hợp lệ", "metrics.json có khớp episode_set_hash của episode set đang xem không.", "boolean", "contract"),
    "parse_errors": ("Lỗi đọc dữ liệu", "Số lỗi parse khi đọc metrics.json hoặc episodes.jsonl.", "count", "contract"),
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
    if RETENTION_TRACK in tracks:
        retention_rows = [
            episode for episode in episodes if episode.get("benchmark_track") == RETENTION_TRACK
        ]
        metrics.update(summarize_retention(retention_rows))
        by_mode: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for episode in retention_rows:
            by_mode[str(episode.get("mode"))].append(episode)
        text = _mode_pass_rate(by_mode.get("text_baseline", []))
        clean = _mode_pass_rate(by_mode.get("clean_voice", []))
        cabin = _mode_pass_rate(by_mode.get("realistic_cabin_voice", []))
        slots_correct = sum(
            episode.get("critical_slot_result", {}).get("correct", 0)
            for episode in episodes
            if isinstance(episode.get("critical_slot_result"), dict)
        )
        slots_total = sum(
            episode.get("critical_slot_result", {}).get("total", 0)
            for episode in episodes
            if isinstance(episode.get("critical_slot_result"), dict)
        )
        metrics.update(
            {
                "text_pass_at_1": text,
                "clean_voice_pass_at_1": clean,
                "cabin_voice_pass_at_1": cabin,
                "clean_voice_retention": clean / text
                if text and clean is not None
                else None,
                "voice_capability_retention": cabin / text
                if text and cabin is not None
                else None,
                "voice_degradation_gap": text - cabin
                if text is not None and cabin is not None
                else None,
                "critical_slot_accuracy": slots_correct / slots_total
                if slots_total
                else None,
            }
        )
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
        overlay = overlays.get(row.get("speech_overlay_id"))
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
            elif row.get("benchmark_track") == RETENTION_TRACK:
                row = evaluate_retention_episode(row, overlay, task)
        except Exception as exc:
            row.setdefault("failure_types", []).append("DASHBOARD_REEVALUATION_ERROR")
            row["primary_failure_type"] = row.get("primary_failure_type") or "DASHBOARD_REEVALUATION_ERROR"
            row["dashboard_reevaluation_error"] = str(exc)
        row["failure_types"] = [str(failure) for failure in (row.get("failure_types") or [])]
        evaluated.append(row)
    return evaluated


def _mode_pass_rate(rows: list[dict[str, Any]]) -> float | None:
    scored = [row for row in rows if _score_pass(row) is not None]
    return _rate(sum(1 for row in scored if _score_pass(row)), len(scored))


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
    if key.startswith("degradation_by_component."):
        parts = key.split(".")
        mode = parts[1] if len(parts) > 1 else "unknown"
        component = parts[2] if len(parts) > 2 else "unknown"
        return (
            f"{mode} {component}",
            "Mức suy giảm giữa text baseline và voice mode theo từng thành phần.",
            "rate",
            "retention_degradation",
        )
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


def _flatten_metrics(metrics: dict[str, Any], latency_summary: list[dict[str, Any]]) -> dict[str, Any]:
    flat: dict[str, Any] = {
        key: value
        for key, value in metrics.items()
        if key not in {"degradation_by_component", "metric_contract", "run_metadata"}
        and not isinstance(value, (dict, list))
    }
    degradation = metrics.get("degradation_by_component")
    if isinstance(degradation, dict):
        for mode, values in degradation.items():
            if not isinstance(values, dict):
                continue
            for component, value in values.items():
                flat[f"degradation_by_component.{mode}.{component}"] = value
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
    retention_only = {"retention", "retention_degradation"}
    fdrc_only = {"fdrc"}
    if selected_track == RETENTION_TRACK and group_id in fdrc_only:
        return False
    if selected_track == FDRC_TRACK and group_id in retention_only:
        return False
    return True


def _catalog_keys(flat_metrics: dict[str, Any], selected_track: str | None) -> list[str]:
    ordered: list[str] = []
    for group in METRIC_GROUPS:
        if not _metric_group_applies(group["id"], selected_track):
            continue
        for key in group["metric_keys"]:
            if key.endswith(".*"):
                prefix = key[:-1]
                ordered.extend(sorted(item for item in flat_metrics if item.startswith(prefix)))
            elif key not in ordered:
                ordered.append(key)
    for key in sorted(flat_metrics):
        if key not in ordered and not isinstance(flat_metrics.get(key), (dict, list)):
            ordered.append(key)
    return ordered


def _metric_status(key: str, value: Any, nullable: bool, contract_violations: set[str]) -> str:
    if key in contract_violations:
        return "invalid"
    if value is None:
        return "nullable_null" if nullable else "missing"
    return "ok"


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
        denominator_payload = (
            denominators.get(key)
            if key in denominators
            else denominators.get(base_key)
        )
        catalog.append(
            {
                "key": key,
                "label": label,
                "description": description,
                "value": value,
                "unit": unit,
                "group": group,
                "track": selected_track,
                "source": metric_source,
                "denominator": denominator_payload,
                "nullable": nullable,
                "null_reason": null_reason,
                "status": _metric_status(key, value, nullable, violations),
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
        [event for event in events if isinstance(event.get("t_ms"), (int, float))],
        key=lambda event: event["t_ms"],
    )
    return [
        {**event, "priority": event.get("event") in PRIORITY_TIMELINE_EVENTS}
        for event in sorted_events
    ]


def _metadata(episodes: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "tracks": _values(episodes, "benchmark_track"),
        "domains": _values(episodes, "domain"),
        "models": _values(episodes, "model"),
        "modes": _values(episodes, "mode"),
        "agents": _values(episodes, "agent"),
        "accent_regions": _values(episodes, "accent_region"),
        "speech_speeds": _values(episodes, "speech_speed"),
        "audio_conditions": _values(episodes, "audio_condition_id"),
    }


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
                    and track in {RETENTION_TRACK, FDRC_TRACK},
                    **metadata,
                }
            )
        return sorted(runs, key=lambda row: row.get("updated_at") or "", reverse=True)

    def leaderboard(self, track: str = "full_duplex_repair_to_commit") -> list[dict[str, Any]]:
        rows = []
        for run in self.list_runs():
            if run.get("benchmark_track") != track:
                continue
            summary = self.run_summary(run["run_id"], track=track)
            metrics = summary.get("metrics", {})
            meta = summary.get("run_metadata", {}) or {}
            rows.append({
                "run_id": run["run_id"],
                "provider": (meta.get("providers") or [None])[0],
                "model": (meta.get("models") or [None])[0],
                "yield_mode": (meta.get("fdrc_yield_modes") or [None])[0],
                "run_kind": run.get("run_kind"),
                "data_provenance": run.get("data_provenance"),
                "episode_count": summary.get("episode_count"),
                "updated_at": run.get("updated_at"),
                "reportability_status": metrics.get("reportability_status"),
                "fdrc_validity_rate": metrics.get("fdrc_validity_rate"),
                "raw_fdrc_pass_at_1": metrics.get("raw_fdrc_pass_at_1"),
                "performance_fdrc_pass_at_1": metrics.get("performance_fdrc_pass_at_1"),
                "performance_yield_latency_p50_ms": metrics.get("performance_yield_latency_p50_ms"),
                "performance_yield_latency_p95_ms": metrics.get("performance_yield_latency_p95_ms"),
                "performance_yield_latency_pass_rate": metrics.get("performance_yield_latency_pass_rate"),
                "forbidden_tool_call_rate": metrics.get("forbidden_tool_call_rate"),
                "cancel_success_rate": metrics.get("cancel_success_rate"),
                "correction_uptake_rate": metrics.get("correction_uptake_rate"),
                "old_intent_suppression_rate": metrics.get("old_intent_suppression_rate"),
            })
        return rows

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

    def run_summary(self, run_id: str, track: str | None = None) -> dict[str, Any]:
        path, metrics, raw_episodes, errors = self._load_run(run_id)
        selected_track = track or _dominant_track(raw_episodes)
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
        display_metrics = {**derived_metrics, **metrics} if metrics_valid else derived_metrics
        metric_source = "metrics.json" if metrics_valid else "episodes.jsonl"
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
        explanation = explain_fdrc_metric(metric_key, scoped) or {
            "key": metric_key,
            "supported": False,
        }
        base = {
            "run_id": run_id,
            "key": metric_key,
            "label": label,
            "description": description,
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
        recomputed = explanation["value"]
        if metrics_valid and metric_key in metrics:
            displayed = metrics.get(metric_key)
        else:
            displayed = recomputed
        if displayed is None and recomputed is None:
            matches = True
        elif isinstance(displayed, (int, float)) and isinstance(recomputed, (int, float)):
            matches = abs(displayed - recomputed) < 1e-9
        else:
            matches = displayed == recomputed
        base.update(
            {
                "supported": True,
                "scope": explanation["scope"],
                "formula_vi": explanation["formula_vi"],
                "row_set_label_vi": explanation["row_set_label_vi"],
                "numerator_label_vi": explanation["numerator_label_vi"],
                "numerator": explanation["numerator"],
                "denominator": explanation["denominator"],
                "value": displayed,
                "recomputed_value": recomputed,
                "value_matches_recomputed": matches,
                "numerator_episodes": numerator_episodes,
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
        mode: str | None = None,
        failure: str | None = None,
        passed: bool | None = None,
        validity: str | None = None,
    ) -> dict[str, Any]:
        _, _, episodes, errors = self._load_run(run_id)
        episodes = _evaluation_view(episodes)
        filtered = episodes
        if track:
            filtered = [episode for episode in filtered if episode.get("benchmark_track") == track]
        if domain:
            filtered = [episode for episode in filtered if episode.get("domain") == domain]
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
                    "retention": {
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
            RETENTION_TRACK: {},
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
                RETENTION_TRACK: {
                    "label": BENCHMARK_LABELS[RETENTION_TRACK],
                    "description": TRACK_DESCRIPTIONS[RETENTION_TRACK],
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
            "retention_audio_modes": ["clean", "cabin_noise"],
            "fdrc_audio_modes": ["interaction_stress"],
        }

    def start_benchmark_run(
        self,
        preset_id: str,
        *,
        domains: str = "automotive,navigation,media_phone",
        personas: str = "vi_north_normal,vi_central_normal,vi_south_normal",
        model: str | None = None,
    ) -> dict[str, Any]:
        preset = RUN_PRESETS.get(preset_id)
        if preset is None:
            raise ValueError(f"Unknown run preset: {preset_id}")
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output = self.results_dir / f"{preset['default_output_prefix']}_{stamp}"
        command = [
            sys.executable,
            "-m",
            f"src.{Path(preset['script']).stem}",
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
