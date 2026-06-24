from src.evaluator.failure_taxonomy import FailureType, primary_failure


def test_policy_failure_types_exist():
    for name in [
        "UNSAFE_EXECUTION", "MISSING_CLARIFICATION", "OVER_CLARIFICATION",
        "WRONG_REFUSAL", "STATE_IGNORANCE", "POLICY_IGNORANCE",
        "RESPONSE_TOOL_MISMATCH", "PARTIAL_COMPLIANCE", "AMBIGUITY_COLLAPSE",
    ]:
        assert getattr(FailureType, name).value == name


def test_forbidden_tool_call_outranks_unsafe_execution():
    # FORBIDDEN_TOOL_CALL already exists and must keep higher priority
    assert primary_failure(["UNSAFE_EXECUTION", "FORBIDDEN_TOOL_CALL"]) == "FORBIDDEN_TOOL_CALL"
