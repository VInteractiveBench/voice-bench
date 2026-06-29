from __future__ import annotations

from copy import deepcopy

from .critical_slot_evaluator import evaluate_critical_slots
from .common import evaluate_common, summarize_shared, tool_call_matches
from .fdrc_contract import summarize_fdrc_contract
from .failure_taxonomy import FailureType, is_blocking, primary_failure
from .operational import (
    argument_match_normalized,
    state_matches_normalized,
    tool_calls_covered,
)
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


def _successful_calls(result: dict) -> list[dict]:
    calls = [call for call in result.get("tool_calls", []) if isinstance(call, dict)]
    results = result.get("tool_results", [])
    if len(results) != len(calls):
        return calls
    return [
        call
        for call, tool_result in zip(calls, results)
        if not isinstance(tool_result, dict) or tool_result.get("success") is not False
    ]


def _last_matching_commit(calls: list[dict], expected_calls: list[dict]) -> dict | None:
    for call in reversed(calls):
        if any(tool_call_matches(expected_call, call) for expected_call in expected_calls):
            return call
    return None


def _last_final_intent_tool_commit(calls: list[dict], expected_calls: list[dict]) -> dict | None:
    expected_tools = {call.get("tool") for call in expected_calls if isinstance(call, dict)}
    if not expected_tools:
        return None
    for call in reversed(calls):
        if call.get("tool") in expected_tools:
            return call
    return None


def _infer_fdrc_captured_slots(overlay: dict, calls: list[dict]) -> dict:
    expected = overlay.get("expected_critical_slots", {})
    if not isinstance(expected, dict) or not expected:
        return {}
    captured: dict = {}
    for call in reversed(calls):
        args = call.get("args", {}) if isinstance(call, dict) else {}
        if not isinstance(args, dict):
            continue
        for key in expected:
            if key in captured:
                continue
            if key == "poi_name":
                value = args.get("dest_name") or args.get("destination") or args.get("query")
            elif key == "contact_name":
                value = args.get("target") or args.get("contact_name")
            else:
                value = args.get(key)
            if value not in (None, ""):
                captured[key] = value
    return captured


def evaluate_fdrc_episode(episode: dict, overlay: dict, task: dict) -> dict:
    fdrc_task = deepcopy(task)
    fdrc_task["expected_final_state"] = overlay.get(
        "expected_final_state", task.get("expected_final_state", {})
    )
    result = evaluate_common(episode, fdrc_task, overlay.get("expected_tool_calls", []))
    calls = result.get("tool_calls", [])
    committed_calls = _successful_calls(result)
    forbidden = overlay.get("forbidden_tool_calls", [])
    expected_calls = overlay.get("expected_tool_calls", [])
    cancelled = overlay.get("final_intent") == "cancel"
    cancel_attempted_tool_call = bool(cancelled and calls)
    cancel_blocked_tool_call_count = (
        sum(
            1
            for tool_result in result.get("tool_results", [])
            if isinstance(tool_result, dict) and tool_result.get("success") is False
        )
        if cancelled
        else 0
    )
    forbidden_scope_calls = calls if cancelled else committed_calls
    forbidden_called = any(
        tool_call_matches(blocked, call) for blocked in forbidden for call in forbidden_scope_calls
    )
    final_commit = _last_matching_commit(committed_calls, expected_calls)
    correction_uptaken = bool(not expected_calls or final_commit is not None)
    expected_slots = overlay.get("expected_critical_slots", {})
    captured_slots = result.get("captured_slots", {})
    inferred_slots = _infer_fdrc_captured_slots(overlay, committed_calls)
    if isinstance(captured_slots, dict):
        captured_slots = {**inferred_slots, **captured_slots}
    else:
        captured_slots = inferred_slots
    result["captured_slots"] = captured_slots
    result["critical_slot_result"] = evaluate_critical_slots(expected_slots, captured_slots)
    final_intent_tool_commit = _last_final_intent_tool_commit(committed_calls, expected_calls)
    repair_intent_mismatch = bool(
        expected_calls
        and final_intent_tool_commit is not None
        and not result["critical_slot_result"].get("passed", True)
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
        sum(tool_call_matches(expected_call, call) for call in committed_calls) > 1
        for expected_call in expected_calls
    )
    continued_old_confirmation = any(
        event.get("event") == "assistant_continued_old_confirmation"
        for event in result.get("voice_events", [])
    )
    fdrc_validity = classify_fdrc_validity(result, overlay)
    if forbidden_called:
        result["failure_types"].extend(
            [FailureType.FORBIDDEN_TOOL_CALL, FailureType.OLD_INTENT_COMMITTED]
        )
        if cancelled:
            result["failure_types"].append(FailureType.CANCEL_NOT_RESPECTED)
    if cancel_attempted_tool_call:
        result["failure_types"].append(FailureType.CANCEL_NOT_RESPECTED)
    if repair_intent_mismatch:
        result["failure_types"].append(FailureType.REPAIR_INTENT_MISMATCH)
    elif not correction_uptaken:
        result["failure_types"].append(FailureType.CORRECTION_NOT_UPTAKEN)
    # Yield latency only applies when a real barge-in occurred (the assistant was
    # already speaking when the interrupt fired). If the provider had not started
    # speaking yet, there is nothing to interrupt, so yield latency is N/A, not a fail.
    if assistant_speaking_before_interrupt and not yield_result["passed"]:
        result["failure_types"].append(FailureType.YIELD_LATENCY_TOO_HIGH)
    if missing_observed:
        result["failure_types"].append(FailureType.MISSING_OBSERVED_EVENT)
    if not fdrc_validity.get("valid"):
        result["failure_types"].extend(fdrc_validity.get("reasons", []))
    # `not assistant_speaking_before_interrupt` is intentionally NOT a policy violation:
    # it reflects response latency (the assistant hadn't started speaking when the
    # interrupt fired), not a policy breach. It is recorded as a diagnostic instead.
    if (
        early_commit
        or commit_before_repair_processed
        or continued_old_confirmation
        or duplicate_final_commit
    ):
        result["failure_types"].append(FailureType.POLICY_VIOLATION)
    final_state_ok = result.get("scores", {}).get("state_match") == 1
    execution_success = len(result.get("tool_results", [])) == len(calls) and all(
        item.get("success") is True for item in result.get("tool_results", [])
    )
    schema_ok = not result.get("validation_errors")
    task_pass = bool(
        (correction_uptaken if not cancelled else not cancel_attempted_tool_call)
        and final_state_ok
        and execution_success
        and schema_ok
    )
    result["scores"]["task_pass"] = int(task_pass)
    if task_pass:
        result["failure_types"] = [
            failure
            for failure in result["failure_types"]
            if failure not in {FailureType.TOOL_SELECTION_ERROR, FailureType.TOOL_ARGUMENT_ERROR}
        ]
    result["failure_types"] = list(dict.fromkeys(result["failure_types"]))
    result["primary_failure_type"] = primary_failure(result["failure_types"])
    result["fdrc_validity"] = fdrc_validity
    result["repair"] = {
        "initial_intent": overlay.get("initial_intent"),
        "final_intent": overlay.get("final_intent"),
        "correction_text": overlay.get("repair_utterance"),
        "old_intent_committed": forbidden_called,
        "correction_uptaken": correction_uptaken,
        "repair_intent_mismatch": repair_intent_mismatch,
        "forbidden_tool_called": forbidden_called,
        "cancel_respected": bool(cancelled and not cancel_attempted_tool_call),
        "cancel_attempted_tool_call": cancel_attempted_tool_call,
        "cancel_tool_call_count": len(calls) if cancelled else 0,
        "cancel_blocked_tool_call_count": cancel_blocked_tool_call_count,
        "tool_call_count": len(calls),
        "duplicate_final_commit": duplicate_final_commit,
        "assistant_speaking_before_interrupt": assistant_speaking_before_interrupt,
        "missing_observed_events": missing_observed,
        "tool_commit_time_ms": final_commit.get("t_ms") if final_commit else next(
            (c.get("t_ms") for c in committed_calls if c.get("t_ms") is not None), None
        ),
    }
    result["latency"] = {
        **result.get("latency", {}),
        "yield_latency_ms": yield_result["yield_latency_ms"],
        "yield_applicable": assistant_speaking_before_interrupt,
    }
    result["scores"]["voice_pass"] = int(
        correction_uptaken
        and not forbidden_called
        and (yield_result["passed"] or not assistant_speaking_before_interrupt)
    )
    result["scores"]["final_pass"] = int(
        result["scores"]["task_pass"]
        and result["scores"]["policy_pass"]
        and result["scores"]["voice_pass"]
        and result["fdrc_validity"].get("valid")
        and not result["failure_types"]
    )
    # --- Operational tier (lenient on false negatives; strict scores untouched) ---
    op_state_match = state_matches_normalized(
        fdrc_task.get("expected_final_state", {}), result.get("final_state", {})
    )
    op_tool_match = tool_calls_covered(expected_calls, committed_calls)
    op_argument_match = argument_match_normalized(expected_calls, committed_calls)
    if cancelled:
        op_correction = not cancel_attempted_tool_call
    else:
        op_correction = op_state_match
    resolved_failures: set[str] = set()
    if op_state_match:
        resolved_failures.add(FailureType.FINAL_STATE_MISMATCH)
    if op_correction:
        resolved_failures.update(
            {FailureType.CORRECTION_NOT_UPTAKEN, FailureType.REPAIR_INTENT_MISMATCH}
        )
    operational_blocking = [
        failure
        for failure in result["failure_types"]
        if failure not in resolved_failures and is_blocking(failure)
    ]
    result["scores"]["operational_state_match"] = int(op_state_match)
    result["scores"]["operational_tool_match"] = int(op_tool_match)
    result["scores"]["operational_argument_match"] = int(op_argument_match)
    result["scores"]["operational_correction_uptaken"] = int(op_correction)
    result["scores"]["operational_final_pass"] = int(
        bool(result["fdrc_validity"].get("valid")) and not operational_blocking
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
