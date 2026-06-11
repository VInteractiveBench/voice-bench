from __future__ import annotations

from copy import deepcopy
from statistics import median

from .common import evaluate_common, summarize_shared, tool_call_matches
from .failure_taxonomy import FailureType, primary_failure
from .voice_event_evaluator import evaluate_yield, event_time


def evaluate_fdrc_episode(episode: dict, overlay: dict, task: dict) -> dict:
    fdrc_task = deepcopy(task)
    fdrc_task["expected_final_state"] = overlay.get(
        "expected_final_state", task.get("expected_final_state", {})
    )
    result = evaluate_common(episode, fdrc_task, overlay.get("expected_tool_calls", []))
    calls = result.get("tool_calls", [])
    forbidden = overlay.get("forbidden_tool_calls", [])
    expected_calls = overlay.get("expected_tool_calls", [])
    forbidden_called = any(
        tool_call_matches(blocked, call) for blocked in forbidden for call in calls
    )
    correction_uptaken = all(
        any(tool_call_matches(expected_call, call) for call in calls)
        for expected_call in expected_calls
    )
    yield_result = evaluate_yield(
        result.get("voice_events", []),
        overlay.get("voice_assertions", {}).get("max_yield_latency_ms", 700),
    )
    interrupt = event_time(overlay.get("voice_timeline", []), "user_interrupt_start")
    assistant_expected_start = event_time(
        overlay.get("voice_timeline", []), "assistant_speech_expected_start"
    )
    assistant_actual_start = event_time(
        result.get("voice_events", []), "assistant_speech_start"
    )
    assistant_start = (
        assistant_actual_start
        if assistant_actual_start is not None
        else assistant_expected_start
    )
    assistant_speaking_before_interrupt = (
        interrupt is not None
        and assistant_start is not None
        and assistant_start < interrupt
    )
    commit_allowed_after = event_time(
        overlay.get("voice_timeline", []), "tool_commit_allowed_after"
    )
    early_commit = any(
        call.get("t_ms") is None
        or (commit_allowed_after is not None and call["t_ms"] < commit_allowed_after)
        for call in calls
    )
    duplicate_final_commit = any(
        sum(tool_call_matches(expected_call, call) for call in calls) > 1
        for expected_call in expected_calls
    )
    continued_old_confirmation = any(
        event.get("event") == "assistant_continued_old_confirmation"
        for event in result.get("voice_events", [])
    )
    cancelled = overlay.get("final_intent") == "cancel"
    if forbidden_called:
        result["failure_types"].extend(
            [FailureType.FORBIDDEN_TOOL_CALL, FailureType.OLD_INTENT_COMMITTED]
        )
        if cancelled:
            result["failure_types"].append(FailureType.CANCEL_NOT_RESPECTED)
    if cancelled and calls:
        result["failure_types"].append(FailureType.CANCEL_NOT_RESPECTED)
    if not correction_uptaken:
        result["failure_types"].append(FailureType.CORRECTION_NOT_UPTAKEN)
    if not yield_result["passed"]:
        result["failure_types"].append(FailureType.YIELD_LATENCY_TOO_HIGH)
    if (
        early_commit
        or continued_old_confirmation
        or duplicate_final_commit
        or not assistant_speaking_before_interrupt
    ):
        result["failure_types"].append(FailureType.POLICY_VIOLATION)
    result["failure_types"] = list(dict.fromkeys(result["failure_types"]))
    result["primary_failure_type"] = primary_failure(result["failure_types"])
    result["repair"] = {
        "initial_intent": overlay.get("initial_intent"),
        "final_intent": overlay.get("final_intent"),
        "correction_text": overlay.get("repair_utterance"),
        "old_intent_committed": forbidden_called,
        "correction_uptaken": correction_uptaken,
        "forbidden_tool_called": forbidden_called,
        "duplicate_final_commit": duplicate_final_commit,
        "assistant_speaking_before_interrupt": assistant_speaking_before_interrupt,
        "tool_commit_time_ms": next(
            (c.get("t_ms") for c in calls if c.get("t_ms") is not None), None
        ),
    }
    result["latency"] = {
        **result.get("latency", {}),
        "yield_latency_ms": yield_result["yield_latency_ms"],
    }
    result["scores"]["voice_pass"] = int(
        correction_uptaken and not forbidden_called and yield_result["passed"]
    )
    result["scores"]["final_pass"] = int(
        result["scores"]["task_pass"]
        and result["scores"]["policy_pass"]
        and result["scores"]["voice_pass"]
        and not result["failure_types"]
    )
    return result


def _rate(rows: list[dict], predicate) -> float:
    return sum(bool(predicate(row)) for row in rows) / len(rows) if rows else 0.0


def _repair_flag(row: dict, field: str, default: bool = False) -> bool:
    return bool(row.get("repair", {}).get(field, default))


def _percentile(values: list[int], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = round((len(ordered) - 1) * percentile)
    return ordered[index]


def summarize_fdrc(episodes: list[dict]) -> dict:
    latencies = [
        e.get("latency", {}).get("yield_latency_ms")
        for e in episodes
        if e.get("latency", {}).get("yield_latency_ms") is not None
    ]
    cancel_rows = [e for e in episodes if e.get("repair", {}).get("final_intent") == "cancel"]
    return {
        **summarize_shared(episodes),
        "fdrc_pass_at_1": _rate(episodes, lambda e: e["scores"]["final_pass"]),
        "correction_uptake_rate": _rate(episodes, lambda e: _repair_flag(e, "correction_uptaken")),
        "old_intent_suppression_rate": _rate(episodes, lambda e: not _repair_flag(e, "old_intent_committed")),
        "forbidden_tool_call_rate": _rate(episodes, lambda e: _repair_flag(e, "forbidden_tool_called")),
        "cancel_success_rate": _rate(cancel_rows, lambda e: not _repair_flag(e, "forbidden_tool_called")),
        "yield_latency_p50_ms": median(latencies) if latencies else None,
        "yield_latency_p95_ms": _percentile(latencies, 0.95),
        "yield_latency_pass_rate": _rate(episodes, lambda e: FailureType.YIELD_LATENCY_TOO_HIGH not in e["failure_types"]),
    }
