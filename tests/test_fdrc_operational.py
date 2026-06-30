from src.dashboard import service as dashboard_service
from src.evaluator.failure_taxonomy import BLOCKING_FAILURES, is_blocking, FailureType
from src.evaluator.operational import (
    normalize_value,
    deep_subset_normalized,
    state_matches_normalized,
    tool_calls_covered,
    argument_match_normalized,
)
from src.evaluator.fdrc_evaluator import evaluate_fdrc_episode, summarize_fdrc


def test_blocking_set_contains_real_failures():
    assert is_blocking(FailureType.POLICY_VIOLATION)
    assert is_blocking(FailureType.VALIDATION_ERROR)
    assert is_blocking(FailureType.FINAL_STATE_MISMATCH)
    assert is_blocking("POLICY_VIOLATION")  # plain string works (StrEnum)


def test_diagnostic_failures_are_not_blocking():
    assert not is_blocking(FailureType.YIELD_LATENCY_TOO_HIGH)
    assert not is_blocking(FailureType.TOOL_SELECTION_ERROR)
    assert not is_blocking(FailureType.MISSING_OBSERVED_EVENT)


def test_unknown_failure_defaults_to_diagnostic():
    assert not is_blocking("SOME_FUTURE_FAILURE")
    assert "SOME_FUTURE_FAILURE" not in BLOCKING_FAILURES


def test_normalize_value_casefold_diacritics_whitespace():
    assert normalize_value("Sport") == normalize_value("sport")
    assert normalize_value("Thể thao") == normalize_value("the  thao")
    assert normalize_value("  Eco Mode ") == normalize_value("eco mode")


def test_normalize_value_passthrough_non_string():
    assert normalize_value(42) == 42
    assert normalize_value(True) is True
    assert normalize_value(None) is None


def test_deep_subset_normalized_matches_case_and_diacritics():
    assert deep_subset_normalized({"mode": "Sport"}, {"mode": "sport", "x": 1})
    assert not deep_subset_normalized({"mode": "Sport"}, {"mode": "eco"})


def test_state_matches_normalized_subset_semantics():
    expected = {"drive": {"mode": "Thể thao"}}
    actual = {"drive": {"mode": "the thao", "rpm": 3000}}
    assert state_matches_normalized(expected, actual)
    assert not state_matches_normalized(expected, {"drive": {"mode": "eco"}})


def test_tool_calls_covered_allows_extra_in_scope_calls():
    expected = [{"tool": "set_drive_mode", "args": {"mode": "Sport"}}]
    committed = [
        {"tool": "search_places", "args": {"q": "x"}},  # benign extra
        {"tool": "set_drive_mode", "args": {"mode": "sport"}},
    ]
    assert tool_calls_covered(expected, committed)
    assert not tool_calls_covered(expected, [{"tool": "search_places", "args": {}}])


def test_argument_match_normalized_only_considers_name_matched_calls():
    expected = [{"tool": "set_drive_mode", "args": {"mode": "Sport"}}]
    committed = [{"tool": "set_drive_mode", "args": {"mode": "sport"}}]
    assert argument_match_normalized(expected, committed)
    assert not argument_match_normalized(
        expected, [{"tool": "set_drive_mode", "args": {"mode": "eco"}}]
    )


def _base_overlay_task():
    # Uses real registry tools so schema / whitelist validation doesn't block tests.
    # drive_system{device=drive_mode, value=...} is a valid MVP tool call.
    # t_ms values on tool_calls prevent the early_commit POLICY_VIOLATION flag.
    overlay = {
        "expected_final_state": {"drive": {"mode": "Sport"}},
        "expected_tool_calls": [
            {"tool": "drive_system", "args": {"device": "drive_mode", "value": "Sport"}}
        ],
        "forbidden_tool_calls": [],
        "final_intent": "set_sport",
        "voice_timeline": [],
        "voice_assertions": {},
    }
    task = {"expected_final_state": {"drive": {"mode": "Sport"}}}
    return overlay, task


def test_operational_pass_when_extra_call_and_casing_differ():
    overlay, task = _base_overlay_task()
    episode = {
        "is_reference": True,
        "benchmark_track": "full_duplex_repair_to_commit",
        "tool_calls": [
            {"tool": "search_places", "args": {"query": "x", "max_results": 1}, "t_ms": 3000},
            {"tool": "drive_system", "args": {"device": "drive_mode", "value": "sport"}, "t_ms": 4000},
        ],
        "tool_results": [{"success": True}, {"success": True}],
        "final_state": {"drive": {"mode": "sport"}},
        "assistant_transcript": ["ok"],
        "normalized_events": [],
        "voice_events": [],
    }
    result = evaluate_fdrc_episode(episode, overlay, task)
    assert result["scores"]["final_pass"] == 0
    assert result["scores"]["operational_final_pass"] == 1
    assert result["scores"]["operational_state_match"] == 1
    assert result["scores"]["operational_tool_match"] == 1


def test_operational_fails_on_blocking_policy_violation():
    overlay, task = _base_overlay_task()
    # Forbidden tool matches the committed call exactly (strict comparison) so
    # FORBIDDEN_TOOL_CALL + OLD_INTENT_COMMITTED are raised — both are blocking
    # and are NOT resolved by the operational tier.
    overlay["forbidden_tool_calls"] = [
        {"tool": "drive_system", "args": {"device": "drive_mode", "value": "sport"}}
    ]
    episode = {
        "is_reference": True,
        "benchmark_track": "full_duplex_repair_to_commit",
        "tool_calls": [
            {"tool": "drive_system", "args": {"device": "drive_mode", "value": "sport"}, "t_ms": 4000}
        ],
        "tool_results": [{"success": True}],
        "final_state": {"drive": {"mode": "sport"}},
        "assistant_transcript": ["ok"],
        "normalized_events": [],
        "voice_events": [],
    }
    result = evaluate_fdrc_episode(episode, overlay, task)
    assert result["scores"]["operational_final_pass"] == 0


def test_operational_never_below_strict_per_episode():
    overlay, task = _base_overlay_task()
    episode = {
        "is_reference": True,
        "benchmark_track": "full_duplex_repair_to_commit",
        "tool_calls": [
            {"tool": "drive_system", "args": {"device": "drive_mode", "value": "Sport"}, "t_ms": 4000}
        ],
        "tool_results": [{"success": True}],
        "final_state": {"drive": {"mode": "Sport"}},
        "assistant_transcript": ["ok"],
        "normalized_events": [],
        "voice_events": [],
    }
    result = evaluate_fdrc_episode(episode, overlay, task)
    assert result["scores"]["operational_final_pass"] >= result["scores"]["final_pass"]


def test_argument_match_normalized_vacuous_when_tool_never_called():
    # tool_calls_covered would return False here; argument_match returns True
    # because there are no matching tool names to check args against.
    assert argument_match_normalized(
        [{"tool": "set_mode", "args": {"mode": "sport"}}], []
    )
    assert not tool_calls_covered([{"tool": "set_mode", "args": {"mode": "sport"}}], [])


def _completed_row(operational_pass: int, strict_pass: int):
    return {
        "benchmark_track": "full_duplex_repair_to_commit",
        "fdrc_validity": {"valid": True},
        "scores": {
            "final_pass": strict_pass,
            "operational_final_pass": operational_pass,
            "operational_state_match": 1,
            "operational_tool_match": 1,
            "operational_argument_match": 1,
            "operational_correction_uptaken": 1,
            "state_match": strict_pass,
            "tool_exact_match": strict_pass,
            "argument_exact_match": strict_pass,
        },
        "failure_types": [],
        "repair": {},
        "latency": {},
    }


def test_summarize_emits_operational_keys_and_monotonic():
    rows = [_completed_row(1, 0), _completed_row(1, 1), _completed_row(0, 0)]
    metrics = summarize_fdrc(rows)
    assert metrics["operational_fdrc_pass_at_1"] == 2 / 3
    assert metrics["raw_fdrc_pass_at_1"] == 1 / 3
    assert metrics["operational_fdrc_pass_at_1"] >= metrics["raw_fdrc_pass_at_1"]
    assert "operational_state_match" in metrics
    assert "operational_correction_uptake_rate" in metrics


def test_operational_metrics_registered_and_in_fdrc_track():
    registry = dashboard_service.METRIC_REGISTRY
    for key in [
        "operational_fdrc_pass_at_1",
        "operational_state_match",
        "operational_tool_match",
        "operational_argument_match",
        "operational_correction_uptake_rate",
    ]:
        assert key in registry, f"{key} missing from METRIC_REGISTRY"

    fdrc_track = next(t for t in dashboard_service.METRIC_GROUPS if t["id"] == "fdrc")
    assert "operational_fdrc_pass_at_1" in fdrc_track["metric_keys"]
