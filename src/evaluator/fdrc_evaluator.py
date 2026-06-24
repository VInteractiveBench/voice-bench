from __future__ import annotations

from copy import deepcopy

from .common import evaluate_common, summarize_shared, tool_call_matches
from .fdrc_contract import summarize_fdrc_contract
from .failure_taxonomy import FailureType, primary_failure
from .fdrc_validity import classify_fdrc_validity, summarize_fdrc_validity
from .voice_event_evaluator import evaluate_yield, event_time


def _is_reference_episode(result: dict) -> bool:
    return bool(result.get("is_reference")) or result.get("run_kind") in {"reference", "sample", "internal"}


def _observed_event_time(events: list[dict], event_name: str) -> int | None:
    return next(
        (
            event.get("t_ms")
            for event in events
            if event.get("event") == event_name
            and event.get("source") == "observed"
            and isinstance(event.get("t_ms"), int)
        ),
        None,
    )


def _event_time_for_episode(result: dict, overlay: dict, event_name: str) -> int | None:
    events = result.get("voice_events", [])
    observed = _observed_event_time(events, event_name)
    if observed is not None:
        return observed
    if _is_reference_episode(result):
        if event_name == "assistant_speech_start":
            return (
                event_time(events, "assistant_speech_start")
                or event_time(events, "assistant_speech_expected_start")
                or event_time(overlay.get("voice_timeline", []), "assistant_speech_expected_start")
            )
        return event_time(events, event_name) or event_time(overlay.get("voice_timeline", []), event_name)
    return None


def _missing_observed_events(result: dict, expected_calls: list[dict]) -> list[str]:
    if _is_reference_episode(result):
        return []
    events = result.get("voice_events", [])
    required = [
        "assistant_speech_start",
        "user_interrupt_start",
        "repair_audio_start",
        "repair_transcript_done",
    ]
    if _observed_event_time(events, "assistant_yielded") is None and _observed_event_time(events, "assistant_speech_stop") is None:
        required.append("assistant_yielded")
    missing = [name for name in required if _observed_event_time(events, name) is None]
    if expected_calls:
        if not any(call.get("t_ms") is not None for call in result.get("tool_calls", [])):
            missing.append("tool_call")
        has_tool_result_event = any(
            event.get("type") == "tool_result" and isinstance(event.get("t_ms"), int)
            for event in result.get("normalized_events", [])
        )
        if (
            len(result.get("tool_results", [])) != len(result.get("tool_calls", []))
            or not has_tool_result_event
        ):
            missing.append("tool_result")
    if not isinstance(result.get("final_state"), dict):
        missing.append("final_state")
    return missing


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
    missing_observed = _missing_observed_events(result, expected_calls)
    yield_result = evaluate_yield(
        result.get("voice_events", []),
        overlay.get("voice_assertions", {}).get("max_yield_latency_ms", 700),
    )
    interrupt = _event_time_for_episode(result, overlay, "user_interrupt_start")
    assistant_start = _event_time_for_episode(result, overlay, "assistant_speech_start")
    repair_transcript_done = _event_time_for_episode(result, overlay, "repair_transcript_done")
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
    commit_before_repair_processed = (
        not _is_reference_episode(result)
        and any(
            repair_transcript_done is None
            or call.get("t_ms") is None
            or call["t_ms"] < repair_transcript_done
            for call in calls
        )
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
    fdrc_validity = classify_fdrc_validity(result, overlay)
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
    if missing_observed:
        result["failure_types"].append(FailureType.MISSING_OBSERVED_EVENT)
    if not fdrc_validity.get("valid"):
        result["failure_types"].extend(fdrc_validity.get("reasons", []))
    if (
        early_commit
        or commit_before_repair_processed
        or continued_old_confirmation
        or duplicate_final_commit
        or not assistant_speaking_before_interrupt
    ):
        result["failure_types"].append(FailureType.POLICY_VIOLATION)
    result["failure_types"] = list(dict.fromkeys(result["failure_types"]))
    result["primary_failure_type"] = primary_failure(result["failure_types"])
    result["fdrc_validity"] = fdrc_validity
    result["repair"] = {
        "initial_intent": overlay.get("initial_intent"),
        "final_intent": overlay.get("final_intent"),
        "correction_text": overlay.get("repair_utterance"),
        "old_intent_committed": forbidden_called,
        "correction_uptaken": correction_uptaken,
        "forbidden_tool_called": forbidden_called,
        "cancel_respected": bool(cancelled and not calls),
        "tool_call_count": len(calls),
        "duplicate_final_commit": duplicate_final_commit,
        "assistant_speaking_before_interrupt": assistant_speaking_before_interrupt,
        "missing_observed_events": missing_observed,
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
        and result["fdrc_validity"].get("valid")
        and not result["failure_types"]
    )
    return result


def summarize_fdrc(episodes: list[dict]) -> dict:
    validity = summarize_fdrc_validity(episodes)
    valid_rows = [
        episode for episode in episodes if episode.get("fdrc_validity", {}).get("valid")
    ]
    raw = summarize_fdrc_contract(episodes)
    valid_contract = summarize_fdrc_contract(valid_rows)
    validity_rate = validity.get("fdrc_validity_rate")
    if validity_rate is None or validity_rate < 0.70:
        reportability_status = "NOT_REPORTABLE"
    elif validity_rate < 0.90:
        reportability_status = "VALIDITY_ONLY"
    else:
        reportability_status = "REPORTABLE_DOMAIN"
    reportable = reportability_status.startswith("REPORTABLE")
    return {
        **summarize_shared(episodes),
        **raw,
        **validity,
        "total_episode_count": len(episodes),
        "reportability_status": reportability_status,
        "raw_fdrc_pass_at_1": raw.get("fdrc_pass_at_1"),
        "performance_fdrc_pass_at_1": (
            valid_contract.get("fdrc_pass_at_1") if reportable else None
        ),
        "performance_yield_latency_p50_ms": (
            valid_contract.get("yield_latency_p50_ms") if reportable else None
        ),
        "performance_yield_latency_p95_ms": (
            valid_contract.get("yield_latency_p95_ms") if reportable else None
        ),
        "performance_yield_latency_pass_rate": (
            valid_contract.get("yield_latency_pass_rate") if reportable else None
        ),
        "performance_metric_contract": valid_contract.get("metric_contract", {}),
    }
