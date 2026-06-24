from __future__ import annotations

from src.evaluator.fdrc_contract import summarize_fdrc_contract
from src.evaluator.fdrc_explain import explain_fdrc_metric, SUPPORTED_EXPLAIN_KEYS


def _episode(**overrides):
    base = {
        "episode_id": "e",
        "benchmark_track": "full_duplex_repair_to_commit",
        "scores": {"final_pass": True, "state_match": True},
        "failure_types": [],
        "validation_errors": [],
        "repair": {
            "final_intent": "repair",
            "old_intent_committed": False,
            "forbidden_tool_called": False,
            "correction_uptaken": True,
        },
        "fdrc_validity": {"valid": True, "reasons": []},
        "tool_calls": [],
        "final_state": {},
    }
    base.update(overrides)
    return base


def _episodes():
    return [
        _episode(episode_id="pass1"),
        _episode(
            episode_id="forbidden1",
            scores={"final_pass": False, "state_match": False},
            failure_types=["FORBIDDEN_TOOL_CALL", "POLICY_VIOLATION"],
            repair={
                "final_intent": "repair",
                "old_intent_committed": True,
                "forbidden_tool_called": True,
                "correction_uptaken": False,
            },
        ),
        _episode(
            episode_id="cancel_ok",
            repair={"final_intent": "cancel", "cancel_respected": True},
            tool_calls=[],
        ),
        _episode(
            episode_id="invalid1",
            fdrc_validity={"valid": False, "reasons": ["INVALID_AUDIO"]},
        ),
    ]


def test_explain_value_matches_contract_for_every_supported_key():
    episodes = _episodes()
    contract = summarize_fdrc_contract(episodes)
    for key in SUPPORTED_EXPLAIN_KEYS:
        if key in {"performance_fdrc_pass_at_1", "raw_fdrc_pass_at_1",
                   "valid_episode_count", "invalid_episode_count", "fdrc_validity_rate"}:
            continue  # validity/scope-specific keys covered separately below
        result = explain_fdrc_metric(key, episodes)
        assert result is not None and result["supported"], key
        expected = contract.get(key)
        if expected is None:
            assert result["value"] is None, key
        else:
            assert abs(result["value"] - expected) < 1e-9, (key, result["value"], expected)


def test_explain_lists_numerator_episode_ids():
    episodes = _episodes()
    forbidden = explain_fdrc_metric("forbidden_tool_call_rate", episodes)
    assert forbidden["numerator"] == 1
    assert forbidden["denominator"] == 4
    assert forbidden["numerator_episode_ids"] == ["forbidden1"]


def test_explain_unsupported_key_returns_supported_false():
    result = explain_fdrc_metric("yield_latency_p50_ms", _episodes())
    assert result is not None
    assert result["supported"] is False
