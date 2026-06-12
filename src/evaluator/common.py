from __future__ import annotations

from copy import deepcopy
from typing import Any

from src.io import deep_subset

from .failure_taxonomy import FailureType, primary_failure
from .tool_schema_validator import validate_tool_schema
from .tool_scope_validator import validate_tool_scope


def tool_call_matches(expected: dict, actual: dict) -> bool:
    return expected["tool"] == actual.get("tool") and deep_subset(
        expected.get("args", {}), actual.get("args", {})
    )


def evaluate_common(episode: dict, task: dict, expected_calls: list[dict] | None = None) -> dict:
    result = deepcopy(episode)
    if "voice_events" not in result and "normalized_events" in result:
        result["voice_events"] = result["normalized_events"]
    calls = result.get("tool_calls", [])
    expected = task.get("expected_tool_calls", []) if expected_calls is None else expected_calls
    expected_tools = {call["tool"] for call in expected}
    failures: list[str] = list(result.get("failure_types", []))
    validation_errors = []
    scope_failures = []

    for call in calls:
        scope_error = validate_tool_scope(call.get("tool", ""), expected_tools)
        if scope_error:
            failures.append(str(scope_error))
            scope_failures.append(str(scope_error))
        errors = validate_tool_schema(call.get("tool", ""), call.get("args", {}))
        if errors:
            failures.append(FailureType.TOOL_ARGUMENT_ERROR)
            validation_errors.extend({"tool": call.get("tool"), **error} for error in errors)

    tool_names_exact = len(calls) == len(expected) and sorted(
        call.get("tool") for call in calls
    ) == sorted(call["tool"] for call in expected)
    tool_exact = len(calls) == len(expected) and all(
        tool_call_matches(wanted, call) for wanted, call in zip(expected, calls)
    )
    argument_exact = tool_exact
    state_match = deep_subset(task.get("expected_final_state", {}), result.get("final_state", {}))
    communication_present = (not task.get("required_communication", True)) or bool(
        result.get("assistant_transcript")
    )
    tool_results = result.get("tool_results", [])
    execution_success = len(tool_results) == len(calls) and all(
        item.get("success") is True for item in tool_results
    )

    if not tool_exact:
        if tool_names_exact:
            failures.append(FailureType.TOOL_ARGUMENT_ERROR)
        elif not scope_failures:
            failures.append(FailureType.TOOL_SELECTION_ERROR)
    if not state_match:
        failures.append(FailureType.FINAL_STATE_MISMATCH)
    if result.get("policy_violations"):
        failures.append(FailureType.POLICY_VIOLATION)
    if not execution_success:
        failures.append(FailureType.FABRICATED_SUCCESS)
    if not communication_present:
        failures.append(FailureType.FABRICATED_SUCCESS)
    failures = list(dict.fromkeys(str(item) for item in failures))
    passed = not failures
    result["validation_errors"] = validation_errors
    result["failure_types"] = failures
    result["primary_failure_type"] = primary_failure(failures)
    result["scores"] = {
        "task_pass": int(tool_exact and state_match and execution_success),
        "policy_pass": int(not result.get("policy_violations") and not validation_errors),
        "voice_pass": 1,
        "final_pass": int(passed),
        "tool_exact_match": int(tool_exact),
        "argument_exact_match": int(argument_exact),
        "state_match": int(state_match),
    }
    return result


def summarize_shared(episodes: list[dict]) -> dict:
    def rate(predicate) -> float:
        return sum(bool(predicate(row)) for row in episodes) / len(episodes) if episodes else 0.0

    return {
        "pass_at_1": rate(lambda row: row["scores"]["final_pass"]),
        "tool_exact_match": rate(lambda row: row["scores"]["tool_exact_match"]),
        "argument_exact_match": rate(lambda row: row["scores"]["argument_exact_match"]),
        "state_match": rate(lambda row: row["scores"]["state_match"]),
        "policy_violation_rate": rate(lambda row: FailureType.POLICY_VIOLATION in row["failure_types"]),
        "tool_validation_error_rate": rate(lambda row: bool(row.get("validation_errors"))),
        "out_of_scope_tool_call_rate": rate(lambda row: FailureType.OUT_OF_SCOPE_TOOL_CALL in row["failure_types"]),
        "hallucinated_tool_rate": rate(lambda row: FailureType.TOOL_NOT_IN_WHITELIST in row["failure_types"]),
    }
