from __future__ import annotations

from src.evaluator.fdrc_contract import summarize_fdrc_contract
from src.evaluator.fdrc_explain import explain_fdrc_metric, SUPPORTED_EXPLAIN_KEYS
from src.evaluator.fdrc_validity import summarize_fdrc_validity


def _episode(**overrides):
    base = {
        "episode_id": "e",
        "benchmark_track": "full_duplex_repair_to_commit",
        "scores": {"final_pass": True, "state_match": True},
        "latency": {"yield_latency_ms": 100},
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
                   "performance_yield_latency_pass_rate",
                   "performance_yield_latency_p50_ms", "performance_yield_latency_p95_ms",
                   "valid_episode_count", "invalid_episode_count", "fdrc_validity_rate"}:
            continue  # performance/raw have no contract counterpart; validity trio checked vs summarize_fdrc_validity below
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


def test_validity_metrics_match_summarize_fdrc_validity():
    episodes = _episodes()  # all are benchmark_track == FDRC, so _rows() == episodes
    validity = summarize_fdrc_validity(episodes)
    assert explain_fdrc_metric("valid_episode_count", episodes)["value"] == validity["valid_episode_count"]
    assert explain_fdrc_metric("invalid_episode_count", episodes)["value"] == validity["invalid_episode_count"]
    rate = explain_fdrc_metric("fdrc_validity_rate", episodes)["value"]
    assert abs(rate - validity["fdrc_validity_rate"]) < 1e-9


def test_explain_supports_latency_percentiles():
    episodes = [
        _episode(episode_id="a", latency={"yield_latency_ms": 100, "yield_applicable": True}),
        _episode(episode_id="b", latency={"yield_latency_ms": 300, "yield_applicable": True}),
        _episode(episode_id="c", latency={"yield_latency_ms": 900, "yield_applicable": True}),
    ]
    p50 = explain_fdrc_metric("yield_latency_p50_ms", episodes)
    p95 = explain_fdrc_metric("yield_latency_p95_ms", episodes)
    assert p50["supported"] is True
    assert p50["value"] == 300.0
    assert p50["denominator"] == 3
    assert p50["denominator_episode_ids"] == ["a", "b", "c"]
    assert p50["calculation_vi"]
    assert p95["value"] == 900.0


def test_explain_supports_performance_yield_latency_pass_rate():
    episodes = [
        _episode(episode_id="valid_ok"),
        _episode(
            episode_id="valid_slow",
            failure_types=["YIELD_LATENCY_TOO_HIGH"],
        ),
        _episode(
            episode_id="invalid_ok",
            fdrc_validity={"valid": False, "reasons": ["INVALID_AUDIO"]},
        ),
    ]
    result = explain_fdrc_metric("performance_yield_latency_pass_rate", episodes)
    assert result["supported"] is True
    assert result["scope"] == "valid"
    assert result["numerator_episode_ids"] == ["valid_ok"]
    assert result["denominator_episode_ids"] == ["valid_ok", "valid_slow"]
    assert result["value"] == 0.5


def test_explain_supports_latency_summary_metrics():
    episodes = [
        _episode(episode_id="a", latency={"yield_latency_ms": 100, "response_latency_ms": 900}),
        _episode(episode_id="b", latency={"yield_latency_ms": 300, "response_latency_ms": 700}),
        _episode(episode_id="c", latency={"yield_latency_ms": 900, "response_latency_ms": 1100}),
    ]
    result = explain_fdrc_metric("latency_summary.yield_latency_ms.max_ms", episodes)
    assert result["supported"] is True
    assert result["value"] == 900.0
    assert result["denominator"] == 3
    assert result["numerator_episode_ids"] == ["c"]
    assert result["denominator_episode_ids"] == ["a", "b", "c"]
    assert result["calculation_vi"]


def test_explain_unsupported_key_returns_supported_false():
    result = explain_fdrc_metric("some_unknown_metric", _episodes())
    assert result is not None
    assert result["supported"] is False
