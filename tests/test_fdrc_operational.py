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
