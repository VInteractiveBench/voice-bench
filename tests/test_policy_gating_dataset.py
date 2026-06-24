from collections import Counter

from src.io import load_base_tasks, load_overlays
from src.runner import reference_episode, evaluate_episodes
from src.evaluator.policy_gating_evaluator import (
    evaluate_policy_gating_episode,
    summarize_policy_gating,
)

TRACK = "voice_policy_command_gating"


def _policy_overlays():
    return [o for o in load_overlays() if o.get("benchmark_track") == TRACK]


def test_no_retention_overlays_remain():
    assert not [o for o in load_overlays() if o.get("benchmark_track") == "text_to_voice_retention"]


def test_seed_has_all_task_types_and_domains():
    overlays = _policy_overlays()
    assert len(overlays) >= 24
    types = Counter(o["task_type"] for o in overlays)
    for t in ["execute_allowed", "clarify_required", "refuse_required", "state_conditioned_pair"]:
        assert types[t] >= 1
    domains = {o["domain"] for o in overlays}
    assert {"automotive", "navigation", "media_phone"}.issubset(domains)
    pairs = Counter(o.get("state_pair_id") for o in overlays if o.get("state_pair_id"))
    assert any(count >= 2 for count in pairs.values())


def test_reference_run_is_fully_compliant():
    tasks = load_base_tasks()
    overlays = _policy_overlays()
    episodes = [
        reference_episode(tasks[o["base_task_id"]], o, "voice_policy_gating", "vi_north_normal")
        for o in overlays
    ]
    evaluated = evaluate_episodes(episodes, overlays, tasks, evaluate_policy_gating_episode)
    summary = summarize_policy_gating(evaluated)
    assert summary["policy_compliance_rate"] == 1.0
    assert summary["forbidden_tool_call_rate"] == 0.0
    assert summary["metric_contract"]["benchmark_status"] == "completed"
