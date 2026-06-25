import json
from pathlib import Path

from src.dashboard.service import DashboardStore
from src.runner import episode_set_hash


def _write_run(root: Path, run_id: str, metrics: dict, episodes: list[dict]) -> None:
    d = root / run_id
    d.mkdir(parents=True)
    (d / "metrics.json").write_text(json.dumps(metrics), encoding="utf-8")
    with (d / "episodes.jsonl").open("w", encoding="utf-8") as fh:
        for ep in episodes:
            fh.write(json.dumps(ep) + "\n")


def test_leaderboard_one_row_per_fdrc_run(tmp_path):
    ep = {
        "benchmark_track": "full_duplex_repair_to_commit",
        "provider": "google", "model": "gemini-x",
        "scores": {
            "final_pass": 1,
            "tool_exact_match": 1,
            "argument_exact_match": 1,
            "state_match": 1,
        },
        "failure_types": [],
        "validation_errors": [],
    }
    _write_run(
        tmp_path, "run_gemini",
        {"fdrc_validity_rate": 1.0, "performance_fdrc_pass_at_1": 0.5,
         "raw_fdrc_pass_at_1": 0.5, "reportability_status": "REPORTABLE_DOMAIN",
         "episode_set_hash": episode_set_hash([ep]),
         "run_metadata": {"providers": ["google"], "models": ["gemini-x"],
                          "fdrc_yield_modes": ["native_yield"]}},
        [ep],
    )
    store = DashboardStore(tmp_path)
    rows = store.leaderboard()
    assert len(rows) == 1
    row = rows[0]
    assert row["run_id"] == "run_gemini"
    assert row["provider"] == "google"
    assert row["model"] == "gemini-x"
    assert row["fdrc_validity_rate"] == 1.0
    assert row["performance_fdrc_pass_at_1"] == 0.5


def test_leaderboard_skips_non_fdrc(tmp_path):
    _write_run(
        tmp_path, "run_text",
        {"run_metadata": {}},
        [{"benchmark_track": "voice_policy_command_gating", "scores": {}}],
    )
    store = DashboardStore(tmp_path)
    assert store.leaderboard() == []


def test_policy_gating_leaderboard_one_row_per_run(tmp_path):
    ep = {
        "benchmark_track": "voice_policy_command_gating",
        "provider": "openai", "model": "gpt-realtime-mini",
        "scores": {"final_pass": 1, "tool_exact_match": 1, "argument_exact_match": 1, "state_match": 1},
        "decision": "execute",
        "policy_gating": {
            "decision_correct": True, "forbidden_called": False, "is_policy_sensitive": False,
            "clarification_made": False, "clarification_correct": False,
            "requires_clarification": False, "expected_behavior": "execute",
            "response_honest": True, "expected_tools": [], "state_pair_id": None,
        },
        "failure_types": [],
        "validation_errors": [],
    }
    _write_run(
        tmp_path, "run_policy",
        {"policy_compliance_rate": 1.0, "forbidden_tool_call_rate": 0.0,
         "metric_contract": {"benchmark_status": "completed"},
         "episode_set_hash": episode_set_hash([ep]),
         "run_metadata": {"providers": ["openai"], "models": ["gpt-realtime-mini"]}},
        [ep],
    )
    store = DashboardStore(tmp_path)
    rows = store.leaderboard(track="voice_policy_command_gating")
    assert len(rows) == 1
    row = rows[0]
    assert row["run_id"] == "run_policy"
    assert row["model"] == "gpt-realtime-mini"
    assert row["policy_compliance_rate"] == 1.0
    assert row["forbidden_tool_call_rate"] == 0.0
    assert row["benchmark_status"] == "completed"
    # default (FDRC) leaderboard excludes policy runs
    assert store.leaderboard() == []
