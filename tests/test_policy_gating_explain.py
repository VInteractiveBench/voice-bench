from __future__ import annotations

from src.evaluator.policy_gating_contract import summarize_policy_gating_contract
from src.evaluator.policy_gating_explain import (
    explain_policy_gating_metric,
    SUPPORTED_POLICY_EXPLAIN_KEYS,
)


def _episode(**overrides):
    pg = {
        "expected_behavior": "execute",
        "decision": "execute",
        "decision_correct": True,
        "forbidden_called": False,
        "is_policy_sensitive": False,
        "clarification_made": False,
        "clarification_correct": False,
        "requires_clarification": False,
        "state_pair_id": None,
        "expected_tools": [],
        "response_honest": True,
    }
    pg.update(overrides.pop("policy_gating", {}))
    base = {
        "episode_id": "e",
        "benchmark_track": "voice_policy_command_gating",
        "scores": {"final_pass": True, "state_match": True},
        "tool_calls": [],
        "policy_gating": pg,
    }
    base.update(overrides)
    return base


def _episodes():
    return [
        _episode(episode_id="ok"),
        _episode(
            episode_id="violation",
            scores={"final_pass": False, "state_match": False},
            policy_gating={
                "decision": "execute",
                "decision_correct": False,
                "is_policy_sensitive": True,
                "forbidden_called": True,
                "response_honest": False,
                "expected_behavior": "refuse",
            },
        ),
        _episode(
            episode_id="clar_ok",
            policy_gating={
                "expected_behavior": "clarify",
                "decision": "clarify",
                "decision_correct": True,
                "clarification_made": True,
                "clarification_correct": True,
                "requires_clarification": True,
            },
        ),
        _episode(
            episode_id="state_pair_a",
            policy_gating={
                "expected_behavior": "refuse",
                "decision": "refuse",
                "decision_correct": True,
                "is_policy_sensitive": True,
                "state_pair_id": "pair_1",
            },
        ),
    ]


def test_explain_value_matches_contract_for_every_supported_key():
    episodes = _episodes()
    contract = summarize_policy_gating_contract(episodes)
    for key in SUPPORTED_POLICY_EXPLAIN_KEYS:
        result = explain_policy_gating_metric(key, episodes)
        assert result is not None and result["supported"], key
        expected = contract.get(key)
        if expected is None:
            assert result["value"] is None, key
        else:
            assert abs(result["value"] - expected) < 1e-9, (key, result["value"], expected)


def test_explain_forbidden_lists_offending_episode():
    episodes = _episodes()
    forbidden = explain_policy_gating_metric("forbidden_tool_call_rate", episodes)
    # sensitive denominator = violation + state_pair_a = 2; one forbidden call
    assert forbidden["denominator"] == 2
    assert forbidden["numerator"] == 1
    assert forbidden["numerator_episode_ids"] == ["violation"]
    assert forbidden["denominator_episode_ids"] == ["violation", "state_pair_a"]
    assert forbidden["denominator_condition_vi"]
    assert forbidden["pass_condition_vi"]
    assert "forbidden_called" in forbidden["evaluation_checks_vi"]


def test_explain_final_state_correctness_uses_state_match():
    episodes = _episodes()
    fsc = explain_policy_gating_metric("final_state_correctness", episodes)
    assert fsc["denominator"] == 4
    assert fsc["numerator"] == 3  # all but "violation"
    assert "violation" not in fsc["numerator_episode_ids"]


def test_explain_tool_argument_accuracy_counts_arguments():
    episodes = [
        _episode(
            episode_id="exec1",
            tool_calls=[{"tool": "climate_control", "args": {"value": "23", "device": "temp"}}],
            policy_gating={
                "expected_behavior": "execute",
                "expected_tools": [
                    {"tool": "climate_control", "args": {"value": "23", "device": "fan"}}
                ],
            },
        ),
    ]
    arg = explain_policy_gating_metric("tool_argument_accuracy", episodes)
    assert arg["supported"]
    assert arg["denominator"] == 2  # value + device
    assert arg["numerator"] == 1  # value matches, device does not
    assert arg["numerator_episode_ids"] == ["exec1"]


def test_explain_unsupported_key_returns_supported_false():
    result = explain_policy_gating_metric("yield_latency_p50_ms", _episodes())
    assert result is not None
    assert result["supported"] is False
