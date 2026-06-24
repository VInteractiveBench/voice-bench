import json

import pytest
from fastapi.testclient import TestClient

from src.dashboard.app import create_app
from src.dashboard.service import DashboardStore, FDRC_TRACK, RunNotFound
from src.evaluator.fdrc_contract import FDRC_REQUIRED_METRICS
from src.fdrc_run_inspector import compare_layers, debug_rows
from src.io import load_base_tasks, load_overlays
from src.runner import metrics_with_metadata, reference_episode


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


def sample_fdrc_episode(**overrides):
    tasks = load_base_tasks()
    overlay = next(row for row in load_overlays() if row["speech_overlay_id"] == "fdrc_vehicle_001")
    task = tasks[overlay["base_task_id"]]
    episode = reference_episode(
        task, overlay, "full_duplex_repair_to_commit", "vi_north_normal"
    )
    episode.update(
        {
            "run_kind": "provider",
            "is_reference": False,
            "agent": "openai_as_vivi",
            "provider": "openai",
            "model": "gpt-realtime-mini",
            "adapter": "openai_realtime",
            "normalized_events": [
                {"type": "assistant_speech_start", "t_ms": 2600},
                {"type": "user_audio_chunk_sent", "t_ms": 3300, "overlap": True},
                {"type": "assistant_speech_stop", "t_ms": 3700},
                {"type": "user_transcript_done", "t_ms": 4200},
                {"type": "tool_result", "t_ms": 4610, "tool": episode["tool_calls"][0]["tool"]},
            ],
        }
    )
    episode.update(overrides)
    return episode


def test_dashboard_store_lists_runs_and_preserves_null_metrics(tmp_path):
    run = tmp_path / "run_a"
    run.mkdir()
    episodes = [sample_episode()]
    write_json(run / "metrics.json", metrics_with_metadata(episodes, {"pass_at_1": 1.0, "voice_capability_retention": None}))
    write_jsonl(run / "episodes.jsonl", episodes)

    store = DashboardStore(tmp_path)
    runs = store.list_runs()
    assert runs[0]["run_id"] == "run_a"
    assert runs[0]["episode_count"] == 1

    summary = store.run_summary("run_a")
    assert summary["metrics"]["pass_at_1"] == 1.0
    assert summary["metrics"]["voice_capability_retention"] is None
    assert summary["metrics_hash_valid"] is True
    assert summary["pass_fail"] == {"passed": 1, "failed": 0, "unscored": 0}


def test_dashboard_store_ignores_stale_metrics_json(tmp_path):
    run = tmp_path / "stale_run"
    run.mkdir()
    write_json(run / "metrics.json", {"pass_at_1": 1.0, "episode_set_hash": "stale"})
    write_jsonl(
        run / "episodes.jsonl",
        [
            sample_episode(
                scores={
                    "final_pass": 0,
                    "tool_exact_match": 0,
                    "argument_exact_match": 0,
                    "state_match": 0,
                },
                failure_types=["TOOL_SELECTION_ERROR"],
            )
        ],
    )

    summary = DashboardStore(tmp_path).run_summary("stale_run")
    assert summary["metric_source"] == "episodes.jsonl"
    assert summary["metrics_hash_valid"] is False
    assert summary["metrics"]["pass_at_1"] == 0.0


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
    episodes = [sample_episode()]
    write_json(run / "metrics.json", metrics_with_metadata(episodes, {"pass_at_1": 1.0}))
    write_jsonl(run / "episodes.jsonl", episodes)

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


def test_fdrc_required_metric_contract_is_non_null_for_scored_run(tmp_path):
    run = tmp_path / "fdrc_run"
    run.mkdir()
    write_jsonl(run / "episodes.jsonl", [sample_fdrc_episode()])

    summary = DashboardStore(tmp_path).run_summary("fdrc_run", track=FDRC_TRACK)
    assert summary["status"] == "completed"
    for key in FDRC_REQUIRED_METRICS:
        assert summary["metrics"][key] is not None, key
    assert summary["metrics"]["cancel_success_rate"] is None
    assert summary["metrics"]["metric_contract"]["null_reasons"]["cancel_success_rate"] == {
        "null_reason": "no_cancel_cases",
        "denominator": 0,
    }
    assert summary["metrics"]["metric_contract"]["violations"] == []


def test_fdrc_api_and_evaluator_contract_metrics_match(tmp_path):
    run = tmp_path / "fdrc_run"
    run.mkdir()
    write_jsonl(run / "episodes.jsonl", [sample_fdrc_episode()])

    comparison = compare_layers("fdrc_run", tmp_path)
    assert comparison["matched"] is True
    rows = debug_rows("fdrc_run", tmp_path)
    assert rows[0]["observed_events_ok"] is True
    assert rows[0]["yield_ms"] == 400

    client = TestClient(create_app(str(tmp_path)))
    response = client.get(f"/api/runs/fdrc_run/summary?track={FDRC_TRACK}")
    assert response.status_code == 200
    metrics = response.json()["metrics"]
    for key in FDRC_REQUIRED_METRICS:
        assert metrics[key] is not None, key


def test_explain_metric_matches_summary_and_is_consistent(tmp_path):
    run = tmp_path / "fdrc_explain_run"
    run.mkdir()
    episodes = [
        sample_fdrc_episode(episode_id="a1"),
        sample_fdrc_episode(episode_id="a2"),
    ]
    write_jsonl(run / "episodes.jsonl", episodes)

    store = DashboardStore(tmp_path)
    summary = store.run_summary("fdrc_explain_run", track=FDRC_TRACK)
    key = "forbidden_tool_call_rate"
    displayed = summary["metrics"].get(key)

    result = store.explain_metric("fdrc_explain_run", key, track=FDRC_TRACK)
    assert result["supported"] is True
    assert result["label"]
    assert result["metric_source"] in {"metrics.json", "episodes.jsonl"}
    assert result["numerator"] == len(result["numerator_episodes"])
    if displayed is None:
        assert result["value"] is None
    else:
        assert abs(result["value"] - displayed) < 1e-9
    listed = {e["episode_id"] for e in result["numerator_episodes"]}
    assert listed <= {"a1", "a2"}


def test_explain_metric_unsupported_key(tmp_path):
    run = tmp_path / "fdrc_explain_run2"
    run.mkdir()
    write_jsonl(run / "episodes.jsonl", [sample_fdrc_episode(episode_id="x")])
    store = DashboardStore(tmp_path)
    result = store.explain_metric("fdrc_explain_run2", "yield_latency_p50_ms", track=FDRC_TRACK)
    assert result["supported"] is False
    assert result["label"]


def test_explain_metric_missing_run_raises(tmp_path):
    store = DashboardStore(tmp_path)
    with pytest.raises(RunNotFound):
        store.explain_metric("does_not_exist", "forbidden_tool_call_rate")


def test_explain_metric_reports_displayed_value_when_metrics_json_valid(tmp_path):
    run = tmp_path / "fdrc_explain_run3"
    run.mkdir()
    episodes = [sample_fdrc_episode(episode_id="a1"), sample_fdrc_episode(episode_id="a2")]
    write_jsonl(run / "episodes.jsonl", episodes)
    # metrics.json with a matching episode_set_hash but a deliberately wrong value
    write_json(run / "metrics.json", metrics_with_metadata(episodes, {"forbidden_tool_call_rate": 0.999}))

    store = DashboardStore(tmp_path)
    result = store.explain_metric("fdrc_explain_run3", "forbidden_tool_call_rate", track=FDRC_TRACK)
    assert result["metric_source"] == "metrics.json"
    assert result["metrics_hash_valid"] is True
    assert result["value"] == 0.999                      # headline = displayed (from metrics.json)
    assert result["recomputed_value"] != 0.999           # recomputed from episodes differs
    assert result["value_matches_recomputed"] is False


def test_synth_null_reason_gates_performance_by_validity():
    from src.dashboard.service import _synth_null_reason
    assert _synth_null_reason(
        "performance_fdrc_pass_at_1", {"reportability_status": "NOT_REPORTABLE"}
    ) == "not_reportable_validity"
    assert _synth_null_reason(
        "performance_yield_latency_p50_ms", {"reportability_status": "VALIDITY_ONLY"}
    ) == "not_reportable_validity"
    assert _synth_null_reason(
        "performance_fdrc_pass_at_1", {"reportability_status": "REPORTABLE_DOMAIN"}
    ) == "no_data"
    assert _synth_null_reason("some_other_metric", {}) == "no_data"
