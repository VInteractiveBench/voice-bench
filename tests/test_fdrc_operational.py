from src.evaluator.failure_taxonomy import BLOCKING_FAILURES, is_blocking, FailureType


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


from src.evaluator.operational import (
    normalize_value,
    deep_subset_normalized,
    state_matches_normalized,
    tool_calls_covered,
    argument_match_normalized,
)


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
