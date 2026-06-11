import json

from fastapi.testclient import TestClient

from speech_interaction.dashboard.app import create_app
from speech_interaction.dashboard.service import DashboardStore


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def write_jsonl(path, rows):
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def sample_episode(**overrides):
    episode = {
        "episode_id": "ep_001:text_baseline:vi_north_normal:test:model",
        "agent": "test_agent",
        "model": "test_model",
        "benchmark_track": "text_to_voice_retention",
        "domain": "automotive",
        "base_task_id": "base_001",
        "speech_overlay_id": "overlay_001",
        "mode": "text_baseline",
        "accent_region": "north",
        "speech_speed": "normal",
        "audio_condition_id": "none",
        "initial_state": {},
        "final_state": {"committed_intent": "base_001"},
        "user_transcript": ["Đặt điều hòa 22 độ."],
        "assistant_transcript": ["Đã đặt điều hòa."],
        "captured_slots": {"temperature": "22"},
        "normalized_events": [
            {"type": "tool_call", "t_ms": 1200, "tool": "climate_control", "args": {"value": "22"}}
        ],
        "voice_events": [],
        "tool_calls": [{"tool": "climate_control", "args": {"value": "22"}, "t_ms": 1200}],
        "tool_results": [{"success": True}],
        "validation_errors": [],
        "policy_violations": [],
        "latency": {"response_latency_ms": 1500, "yield_latency_ms": None},
        "scores": {
            "final_pass": 1,
            "tool_exact_match": 1,
            "argument_exact_match": 1,
            "state_match": 1,
        },
        "failure_types": [],
        "primary_failure_type": None,
        "critical_slot_result": {"passed": True, "correct": 1, "total": 1},
    }
    episode.update(overrides)
    return episode


def test_dashboard_store_lists_runs_and_preserves_null_metrics(tmp_path):
    run = tmp_path / "run_a"
    run.mkdir()
    write_json(run / "metrics.json", {"pass_at_1": 1.0, "voice_capability_retention": None})
    write_jsonl(run / "episodes.jsonl", [sample_episode()])

    store = DashboardStore(tmp_path)
    runs = store.list_runs()
    assert runs[0]["run_id"] == "run_a"
    assert runs[0]["episode_count"] == 1

    summary = store.run_summary("run_a")
    assert summary["metrics"]["pass_at_1"] == 1.0
    assert summary["metrics"]["voice_capability_retention"] is None
    assert summary["pass_fail"] == {"passed": 1, "failed": 0, "unscored": 0}


def test_dashboard_store_summarizes_run_without_metrics(tmp_path):
    run = tmp_path / "run_without_metrics"
    run.mkdir()
    write_jsonl(
        run / "episodes.jsonl",
        [
            sample_episode(mode="clean_voice"),
            sample_episode(
                episode_id="ep_002",
                mode="clean_voice",
                scores={
                    "final_pass": 0,
                    "tool_exact_match": 0,
                    "argument_exact_match": 0,
                    "state_match": 0,
                },
                failure_types=["TOOL_SELECTION_ERROR"],
                primary_failure_type="TOOL_SELECTION_ERROR",
            ),
        ],
    )

    summary = DashboardStore(tmp_path).run_summary("run_without_metrics")
    assert summary["status"] == "partial"
    assert summary["metric_source"] == "episodes.jsonl"
    assert summary["metrics"]["pass_at_1"] == 0.5
    assert summary["failure_counts"] == [{"key": "TOOL_SELECTION_ERROR", "count": 1}]


def test_dashboard_store_reports_malformed_episode_rows(tmp_path):
    run = tmp_path / "bad_run"
    run.mkdir()
    (run / "episodes.jsonl").write_text(
        json.dumps(sample_episode(), ensure_ascii=False) + "\n{bad json\n",
        encoding="utf-8",
    )

    summary = DashboardStore(tmp_path).run_summary("bad_run")
    assert summary["episode_count"] == 1
    assert summary["status"] == "partial"
    assert summary["parse_errors"][0]["line"] == 2


def test_dashboard_api_endpoints(tmp_path):
    run = tmp_path / "api_run"
    run.mkdir()
    write_json(run / "metrics.json", {"pass_at_1": 1.0})
    write_jsonl(run / "episodes.jsonl", [sample_episode()])

    client = TestClient(create_app(str(tmp_path)))
    runs = client.get("/api/runs")
    assert runs.status_code == 200
    assert runs.json()[0]["run_id"] == "api_run"

    summary = client.get("/api/runs/api_run/summary")
    assert summary.status_code == 200
    assert summary.json()["metrics"]["pass_at_1"] == 1.0

    episodes = client.get("/api/runs/api_run/episodes?passed=true")
    assert episodes.status_code == 200
    assert episodes.json()["count"] == 1

    episode_id = sample_episode()["episode_id"]
    detail = client.get(f"/api/runs/api_run/episodes/{episode_id}")
    assert detail.status_code == 200
    assert detail.json()["summary"]["episode_id"] == episode_id
    assert detail.json()["timeline"][0]["event"] == "tool_call"
