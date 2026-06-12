from __future__ import annotations

from collections import Counter
from typing import Any

from src.evaluator.failure_taxonomy import FailureType, primary_failure
from src.evaluator.tool_schema_validator import validate_tool_schema
from src.evaluator.tool_scope_validator import validate_tool_scope
from src.evaluator.voice_event_evaluator import event_time as _event_time

ValidationIssue = dict[str, Any]

RETENTION_TRACK = "text_to_voice_retention"
FDRC_TRACK = "full_duplex_repair_to_commit"

MODE_TO_AUDIO_CONDITION: dict[str, str] = {
    "text_baseline": "none",
    "clean_voice": "clean",
    "realistic_cabin_voice": "cabin_noise",
    "full_duplex_repair_to_commit": "interaction_stress",
}

COMMON_TASK_FIELDS = {
    "id": str,
    "domain": str,
    "user_goal": str,
    "initial_state": dict,
    "expected_tool_calls": list,
    "expected_final_state": dict,
    "expected_critical_slots": dict,
}

COMMON_OVERLAY_FIELDS = {
    "speech_overlay_id": str,
    "base_task_id": str,
    "domain": str,
    "benchmark_track": str,
    "mode": str,
    "accent_region": str,
    "speech_speed": str,
    "audio_condition_id": str,
    "expected_critical_slots": dict,
    "voice_assertions": dict,
}

FDRC_OVERLAY_FIELDS = {
    "initial_spoken_utterance": str,
    "repair_utterance": str,
    "initial_intent": dict,
    "final_intent": str,
    "voice_timeline": list,
    "forbidden_tool_calls": list,
    "expected_tool_calls": list,
    "expected_final_state": dict,
}

REQUIRED_FDRC_EVENTS = {
    "user_speech_start",
    "assistant_speech_expected_start",
    "user_interrupt_start",
    "assistant_should_yield_by",
    "tool_commit_allowed_after",
}

EPISODE_FIELDS = {
    "episode_id": str,
    "base_task_id": str,
    "speech_overlay_id": str,
    "benchmark_track": str,
    "domain": str,
    "mode": str,
    "initial_state": dict,
    "final_state": dict,
    "user_transcript": list,
    "assistant_transcript": list,
    "captured_slots": dict,
    "tool_calls": list,
    "tool_results": list,
    "voice_events": list,
    "latency": dict,
}


def _issue(path: str, reason: str, *, value: Any = None) -> ValidationIssue:
    issue: ValidationIssue = {"field": path, "reason": reason}
    if value is not None:
        issue["value"] = value
    return issue


def _validate_fields(row: dict, fields: dict[str, type], prefix: str) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for field, kind in fields.items():
        path = f"{prefix}.{field}" if prefix else field
        if field not in row:
            issues.append(_issue(path, "required"))
        elif not isinstance(row[field], kind):
            issues.append(_issue(path, "invalid_type", value=type(row[field]).__name__))
    return issues


def validate_tool_call_contract(call: Any, path: str) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if not isinstance(call, dict):
        return [_issue(path, "invalid_type", value=type(call).__name__)]
    if not isinstance(call.get("tool"), str):
        issues.append(_issue(f"{path}.tool", "required_string"))
        return issues
    if not isinstance(call.get("args"), dict):
        issues.append(_issue(f"{path}.args", "required_object"))
        return issues
    scope_error = validate_tool_scope(call["tool"])
    if scope_error:
        issues.append(_issue(f"{path}.tool", str(scope_error), value=call["tool"]))
    for error in validate_tool_schema(call["tool"], call["args"]):
        issues.append(_issue(f"{path}.args.{error['field']}", error["reason"]))
    if "t_ms" in call and not isinstance(call["t_ms"], int):
        issues.append(_issue(f"{path}.t_ms", "invalid_type", value=type(call["t_ms"]).__name__))
    return issues


def validate_voice_events(events: Any, path: str) -> list[ValidationIssue]:
    if not isinstance(events, list):
        return [_issue(path, "invalid_type", value=type(events).__name__)]
    issues: list[ValidationIssue] = []
    previous_t_ms = -1
    for index, event in enumerate(events):
        item_path = f"{path}[{index}]"
        if not isinstance(event, dict):
            issues.append(_issue(item_path, "invalid_type", value=type(event).__name__))
            continue
        event_name = event.get("event")
        if not isinstance(event_name, str):
            issues.append(_issue(f"{item_path}.event", "required_string"))
        t_ms = event.get("t_ms")
        if not isinstance(t_ms, int):
            issues.append(_issue(f"{item_path}.t_ms", "required_integer"))
            continue
        if t_ms < 0:
            issues.append(_issue(f"{item_path}.t_ms", "negative_time"))
        if t_ms < previous_t_ms:
            issues.append(_issue(f"{item_path}.t_ms", "non_monotonic_time"))
        previous_t_ms = t_ms
    return issues


def validate_base_task(task: Any, path: str = "task") -> list[ValidationIssue]:
    if not isinstance(task, dict):
        return [_issue(path, "invalid_type", value=type(task).__name__)]
    issues = _validate_fields(task, COMMON_TASK_FIELDS, path)
    for index, call in enumerate(task.get("expected_tool_calls", [])):
        issues.extend(validate_tool_call_contract(call, f"{path}.expected_tool_calls[{index}]"))
    return issues


def validate_overlay(overlay: Any, tasks: dict[str, dict], path: str = "overlay") -> list[ValidationIssue]:
    if not isinstance(overlay, dict):
        return [_issue(path, "invalid_type", value=type(overlay).__name__)]
    issues = _validate_fields(overlay, COMMON_OVERLAY_FIELDS, path)
    track = overlay.get("benchmark_track")
    base_task_id = overlay.get("base_task_id")
    task = tasks.get(base_task_id) if isinstance(base_task_id, str) else None
    if task is None:
        issues.append(_issue(f"{path}.base_task_id", "unknown_task", value=base_task_id))
    elif overlay.get("domain") != task.get("domain"):
        issues.append(_issue(f"{path}.domain", "domain_mismatch", value=overlay.get("domain")))
    if track == RETENTION_TRACK:
        if not isinstance(overlay.get("spoken_utterance"), str):
            issues.append(_issue(f"{path}.spoken_utterance", "required_string"))
    elif track == FDRC_TRACK:
        issues.extend(_validate_fields(overlay, FDRC_OVERLAY_FIELDS, path))
        timeline = overlay.get("voice_timeline", [])
        issues.extend(validate_voice_events(timeline, f"{path}.voice_timeline"))
        event_names = {event.get("event") for event in timeline if isinstance(event, dict)}
        for event_name in sorted(REQUIRED_FDRC_EVENTS - event_names):
            issues.append(_issue(f"{path}.voice_timeline", f"missing_{event_name}"))
        interrupt = _event_time(timeline, "user_interrupt_start")
        commit_allowed = _event_time(timeline, "tool_commit_allowed_after")
        if interrupt is not None and commit_allowed is not None and commit_allowed <= interrupt:
            issues.append(_issue(f"{path}.voice_timeline", "commit_allowed_before_interrupt"))
        for field in ("expected_tool_calls", "forbidden_tool_calls"):
            for index, call in enumerate(overlay.get(field, [])):
                issues.extend(validate_tool_call_contract(call, f"{path}.{field}[{index}]"))
        for index, call in enumerate([overlay.get("initial_intent")]):
            issues.extend(validate_tool_call_contract(call, f"{path}.initial_intent[{index}]"))
        if overlay.get("final_intent") == "cancel" and overlay.get("expected_tool_calls"):
            issues.append(_issue(f"{path}.expected_tool_calls", "cancel_must_not_commit_tool"))
        if _has_exact_call_overlap(
            overlay.get("expected_tool_calls", []), overlay.get("forbidden_tool_calls", [])
        ):
            issues.append(_issue(path, "expected_call_overlaps_forbidden_call"))
    else:
        issues.append(_issue(f"{path}.benchmark_track", "unknown_track", value=track))
    return issues


def validate_episode_log(episode: Any, overlay: dict, task: dict) -> list[ValidationIssue]:
    if not isinstance(episode, dict):
        return [_issue("episode", "invalid_type", value=type(episode).__name__)]
    issues = _validate_fields(episode, EPISODE_FIELDS, "episode")
    checks = {
        "base_task_id": task.get("id"),
        "speech_overlay_id": overlay.get("speech_overlay_id"),
        "benchmark_track": overlay.get("benchmark_track"),
        "domain": task.get("domain"),
    }
    for field, expected in checks.items():
        if field in episode and episode.get(field) != expected:
            issues.append(_issue(f"episode.{field}", "mismatch", value=episode.get(field)))
    for index, call in enumerate(episode.get("tool_calls", [])):
        issues.extend(validate_tool_call_contract(call, f"episode.tool_calls[{index}]"))
    for index, result in enumerate(episode.get("tool_results", [])):
        if not isinstance(result, dict):
            issues.append(_issue(f"episode.tool_results[{index}]", "invalid_type", value=type(result).__name__))
    issues.extend(validate_voice_events(episode.get("voice_events", []), "episode.voice_events"))
    if isinstance(episode.get("tool_calls"), list) and isinstance(episode.get("tool_results"), list):
        if len(episode["tool_results"]) != len(episode["tool_calls"]):
            issues.append(_issue("episode.tool_results", "tool_result_count_mismatch"))
    if overlay.get("benchmark_track") == FDRC_TRACK:
        if _event_time(episode.get("voice_events", []), "user_interrupt_start") is None:
            issues.append(_issue("episode.voice_events", "missing_user_interrupt_start"))
    return issues


def preflight_validate_assets(
    tasks: dict[str, dict],
    overlays: list[dict],
    *,
    require_mvp_counts: bool = True,
) -> None:
    issues: list[ValidationIssue] = []
    for task_id, task in tasks.items():
        issues.extend(validate_base_task(task, f"task[{task_id}]"))
    for index, overlay in enumerate(overlays):
        issues.extend(validate_overlay(overlay, tasks, f"overlay[{index}]"))
    if require_mvp_counts:
        tracks = Counter(row.get("benchmark_track") for row in overlays)
        if tracks != {RETENTION_TRACK: 30, FDRC_TRACK: 30}:
            issues.append(_issue("overlays", "mvp_track_count_mismatch", value=dict(tracks)))
        retention_domains = Counter(
            row.get("domain") for row in overlays if row.get("benchmark_track") == RETENTION_TRACK
        )
        if retention_domains != {"automotive": 10, "navigation": 10, "media_phone": 10}:
            issues.append(_issue("overlays", "retention_domain_count_mismatch", value=dict(retention_domains)))
    if issues:
        preview = "; ".join(f"{item['field']}:{item['reason']}" for item in issues[:8])
        raise ValueError(f"Benchmark asset preflight failed with {len(issues)} issue(s): {preview}")


def invalid_episode_result(episode: Any, errors: list[ValidationIssue]) -> dict:
    base = episode.copy() if isinstance(episode, dict) else {"episode_id": None}
    failure_values = {item.value for item in FailureType}
    classified_errors = [
        error["reason"] for error in errors if error.get("reason") in failure_values
    ]
    failures = list(
        dict.fromkeys(
            [*base.get("failure_types", []), *classified_errors, FailureType.VALIDATION_ERROR]
        )
    )
    base["validation_errors"] = [*base.get("validation_errors", []), *errors]
    base["failure_types"] = [str(item) for item in failures]
    base["primary_failure_type"] = primary_failure(base["failure_types"])
    base["scores"] = {
        "task_pass": 0,
        "policy_pass": 0,
        "voice_pass": 0,
        "final_pass": 0,
        "tool_exact_match": 0,
        "argument_exact_match": 0,
        "state_match": 0,
    }
    return base


def _has_exact_call_overlap(expected: list[dict], forbidden: list[dict]) -> bool:
    return any(
        wanted.get("tool") == blocked.get("tool")
        and wanted.get("args", {}) == blocked.get("args", {})
        for wanted in expected
        for blocked in forbidden
    )
