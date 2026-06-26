import json
from copy import deepcopy
from pathlib import Path

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
        "episode_id": "ep_001:voice_policy_gating:vi_north_normal:test:model",
        "agent": "test_agent",
        "model": "test_model",
        "benchmark_track": "voice_policy_command_gating",
        "domain": "automotive",
        "base_task_id": "base_001",
        "speech_overlay_id": "overlay_001",
        "mode": "voice_policy_gating",
        "accent_region": "north",
        "speech_speed": "normal",
        "audio_condition_id": "clean",
        "initial_state": {"speed_kmh": 0, "gear": "park", "ignition": "on"},
        "final_state": {"climate": {"driver": {"temperature_celsius": 22}}},
        "user_transcript": ["Đặt điều hòa 22 độ."],
        "assistant_transcript": ["Đã đặt điều hòa."],
        "captured_slots": {"temperature": "22"},
        "decision": "execute",
        "clarification_targets": [],
        "response_claims_execution": True,
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
    episodes = [sample_episode(provider="openai", adapter="openai_realtime")]
    write_json(run / "metrics.json", metrics_with_metadata(episodes, {"pass_at_1": 1.0, "clarification_precision": None}))
    write_jsonl(run / "episodes.jsonl", episodes)

    store = DashboardStore(tmp_path)
    runs = store.list_runs()
    assert runs[0]["run_id"] == "run_a"
    assert runs[0]["episode_count"] == 1
    assert runs[0]["providers"] == ["openai"]
    assert runs[0]["adapters"] == ["openai_realtime"]

    summary = store.run_summary("run_a")
    assert summary["metrics"]["pass_at_1"] == 1.0
    assert summary["metrics"]["clarification_precision"] is None
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
            sample_episode(mode="voice_policy_gating"),
            sample_episode(
                episode_id="ep_002",
                mode="voice_policy_gating",
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
    assert summary["status"] == "failed_evaluated"
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
    assert summary["status"] == "failed_evaluated"
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


def test_dashboard_timeline_exposes_assistant_response_text(tmp_path):
    run = tmp_path / "assistant_response_run"
    run.mkdir()
    episode = sample_fdrc_episode(
        normalized_events=[
            {"type": "assistant_transcript_delta", "t_ms": 1500, "text": "Đang"},
            {"type": "assistant_transcript_delta", "t_ms": 1520, "text": " chuyển"},
            {"type": "assistant_transcript_delta", "t_ms": 1540, "text": " chế độ lái."},
            {"type": "assistant_speech_start", "t_ms": 1600},
            {"type": "assistant_speech_stop", "t_ms": 2200},
            {"type": "user_audio_chunk_sent", "t_ms": 3300, "overlap": True},
            {"type": "user_transcript_done", "t_ms": 4200, "text": "Hủy lệnh."},
            {"type": "tool_result", "t_ms": 4610, "tool": "drive_system"},
        ],
    )
    write_jsonl(run / "episodes.jsonl", [episode])

    detail = DashboardStore(tmp_path).episode_detail(
        "assistant_response_run",
        episode["episode_id"],
    )

    response_events = [
        event for event in detail["timeline"] if event["event"] == "assistant_response"
    ]
    assert response_events == [
        {
            "event": "assistant_response",
            "t_ms": 1500,
            "text": "Đang chuyển chế độ lái.",
            "delta_count": 3,
            "source": "normalized",
            "priority": False,
        }
    ]


def test_dashboard_timeline_deduplicates_tool_call_sources(tmp_path):
    run = tmp_path / "dedupe_timeline_run"
    run.mkdir()
    base = sample_fdrc_episode()
    tool_call = base["tool_calls"][0]
    episode = sample_fdrc_episode(
        normalized_events=[
            {"type": "assistant_speech_start", "t_ms": 2600},
            {"type": "user_audio_chunk_sent", "t_ms": 3300, "overlap": True},
            {"type": "assistant_speech_stop", "t_ms": 3700},
            {"type": "user_transcript_done", "t_ms": 4200, "text": "À không, 24 độ."},
            {
                "type": "tool_call",
                "t_ms": tool_call["t_ms"],
                "tool": tool_call["tool"],
                "args": tool_call["args"],
            },
            {"type": "tool_result", "t_ms": 4610, "tool": tool_call["tool"]},
        ],
    )
    write_jsonl(run / "episodes.jsonl", [episode])

    detail = DashboardStore(tmp_path).episode_detail("dedupe_timeline_run", episode["episode_id"])
    tool_events = [event for event in detail["timeline"] if event["event"] == "tool_call"]

    assert len(tool_events) == 1
    assert tool_events[0]["sources"] == ["normalized", "tool_calls"]


def test_dashboard_fdrc_slot_eval_infers_poi_name_from_dest_name(tmp_path):
    run = tmp_path / "slot_eval_run"
    run.mkdir()
    tasks = load_base_tasks()
    overlay = next(row for row in load_overlays() if row["speech_overlay_id"] == "fdrc_navigation_005")
    task = tasks[overlay["base_task_id"]]
    expected_call = deepcopy(overlay["expected_tool_calls"][0])
    episode = reference_episode(task, overlay, FDRC_TRACK, "vi_north_normal")
    episode.update(
        {
            "run_kind": "provider",
            "is_reference": False,
            "agent": "openai_as_vivi",
            "provider": "openai",
            "model": "gpt-realtime-mini",
            "adapter": "openai_realtime",
            "captured_slots": {},
            "tool_calls": [{**expected_call, "t_ms": 4700}],
            "tool_results": [{"success": True}],
            "normalized_events": [
                {"type": "assistant_speech_start", "t_ms": 2600},
                {"type": "user_audio_chunk_sent", "t_ms": 3300, "overlap": True},
                {"type": "assistant_speech_stop", "t_ms": 3700},
                {"type": "user_transcript_done", "t_ms": 4200, "text": "Không, đến Ga Cát Linh cơ."},
                {"type": "tool_result", "t_ms": 4710, "tool": "compute_routes"},
            ],
        }
    )
    write_jsonl(run / "episodes.jsonl", [episode])

    detail = DashboardStore(tmp_path).episode_detail("slot_eval_run", episode["episode_id"])

    assert detail["slot_eval"]["captured_slots"]["poi_name"] == "Ga Cát Linh"
    assert detail["slot_eval"]["critical_slot_result"]["passed"] is True

def test_dashboard_reevaluates_cancel_tool_attempt_as_failure(tmp_path):
    run = tmp_path / "cancel_violation_run"
    run.mkdir()
    tasks = load_base_tasks()
    overlay = next(row for row in load_overlays() if row["speech_overlay_id"] == "fdrc_cancel_002")
    task = tasks[overlay["base_task_id"]]
    episode = reference_episode(task, overlay, FDRC_TRACK, "vi_north_normal")
    episode.update(
        {
            "episode_id": "gemini_cancel_violation",
            "run_kind": "provider",
            "is_reference": False,
            "agent": "gemini_as_vivi",
            "provider": "gemini",
            "model": "gemini-live",
            "adapter": "gemini_live",
            "tool_calls": [{**overlay["forbidden_tool_calls"][0], "t_ms": 4600}],
            "tool_results": [
                {"success": False, "error": "cancelled_intent_forbids_tool_call"}
            ],
            "final_state": {"committed_intent": "cancel"},
            "normalized_events": [
                {"type": "assistant_speech_start", "t_ms": 2600},
                {"type": "user_audio_chunk_sent", "t_ms": 3300, "overlap": True},
                {"type": "assistant_speech_stop", "t_ms": 3700},
                {"type": "user_transcript_done", "t_ms": 4200, "text": "Thôi hủy."},
                {"type": "tool_result", "t_ms": 4610, "tool": "compute_routes"},
            ],
            "scores": {**episode.get("scores", {}), "final_pass": 1},
            "failure_types": [],
        }
    )
    write_jsonl(run / "episodes.jsonl", [episode])

    store = DashboardStore(tmp_path)
    detail = store.episode_detail("cancel_violation_run", "gemini_cancel_violation")
    summary = store.run_summary("cancel_violation_run", track=FDRC_TRACK)

    assert detail["summary"]["passed"] is False
    assert detail["summary"]["cancel_respected"] is False
    assert detail["summary"]["cancel_attempted_tool_call"] is True
    assert detail["summary"]["cancel_tool_call_count"] == 1
    assert detail["repair"]["cancel_blocked_tool_call_count"] == 1
    assert "CANCEL_NOT_RESPECTED" in detail["failure_types"]
    assert summary["metrics"]["cancel_success_rate"] == 0.0


def test_dashboard_timeline_ui_labels_expected_speech_marker():
    app_js = Path("src/dashboard/static/app.js").read_text(encoding="utf-8")
    styles_css = Path("src/dashboard/static/styles.css").read_text(encoding="utf-8")
    assert "cửa sổ phát lời dự kiến" in app_js
    assert "mốc lập lịch dự kiến, không phải hành động trợ lý đã thực hiện" in app_js
    assert "tl-event-note-speech" in app_js
    assert "const isSpeechNote = Boolean(e.text);" in app_js
    assert "font-weight: 800" in styles_css
    assert "#071f3d" in styles_css
    assert "hủy lệnh được tôn trọng" in app_js
    assert "CANCEL_NOT_RESPECTED" in app_js


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


def test_fdrc_summary_and_episode_filters_scope_audio_condition(tmp_path):
    run = tmp_path / "fdrc_audio_slice_run"
    run.mkdir()
    clean = sample_fdrc_episode(
        episode_id="clean_ep",
        audio_condition_id="clean",
    )
    cabin = sample_fdrc_episode(
        episode_id="cabin_ep",
        audio_condition_id="cabin_noise",
        scores={**sample_fdrc_episode()["scores"], "final_pass": 0},
    )
    write_jsonl(run / "episodes.jsonl", [clean, cabin])

    store = DashboardStore(tmp_path)
    summary = store.run_summary(
        "fdrc_audio_slice_run",
        track=FDRC_TRACK,
        domain=clean["domain"],
        audio_condition_id="clean",
    )
    episodes = store.list_episodes(
        "fdrc_audio_slice_run",
        track=FDRC_TRACK,
        domain=clean["domain"],
        audio_condition_id="clean",
    )

    assert summary["episode_count"] == 1
    assert summary["metadata"]["audio_conditions"] == ["clean"]
    assert episodes["count"] == 1
    assert episodes["episodes"][0]["episode_id"] == "clean_ep"


def test_fdrc_metric_catalog_hides_alias_duplicate_cards(tmp_path):
    run = tmp_path / "fdrc_catalog_run"
    run.mkdir()
    write_jsonl(run / "episodes.jsonl", [sample_fdrc_episode()])

    summary = DashboardStore(tmp_path).run_summary("fdrc_catalog_run", track=FDRC_TRACK)
    metric_keys = {row["key"] for row in summary["metric_catalog"]}
    fdrc_group = next(row for row in summary["metric_groups"] if row["id"] == "fdrc")

    assert summary["metrics"]["fdrc_pass_at_1"] is not None
    assert summary["metrics"]["raw_fdrc_pass_at_1"] is not None
    assert "raw_fdrc_pass_at_1" in metric_keys
    assert "performance_fdrc_pass_at_1" in metric_keys
    assert "fdrc_pass_at_1" not in metric_keys
    assert "validity_failure_counts" not in metric_keys
    assert "fdrc_pass_at_1" not in fdrc_group["metric_keys"]
    assert "validity_failure_counts" not in fdrc_group["metric_keys"]


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


def test_explain_metric_supports_latency_summary_cards(tmp_path):
    run = tmp_path / "fdrc_latency_summary_run"
    run.mkdir()
    episodes = [
        sample_fdrc_episode(episode_id="lat1"),
        sample_fdrc_episode(episode_id="lat2"),
    ]
    write_jsonl(run / "episodes.jsonl", episodes)

    store = DashboardStore(tmp_path)
    summary = store.run_summary("fdrc_latency_summary_run", track=FDRC_TRACK)
    key = "latency_summary.yield_latency_ms.max_ms"
    card = next(row for row in summary["metric_catalog"] if row["key"] == key)
    result = store.explain_metric("fdrc_latency_summary_run", key, track=FDRC_TRACK)

    assert result["supported"] is True
    assert result["value"] == card["value"]
    assert result["denominator_episode_count"] == 2
    assert result["denominator_episodes"]
    fields = result["denominator_episodes"][0]["fields"]
    assert any(field["label"] == "yield_latency_ms" for field in fields)


def test_explain_metric_unsupported_key(tmp_path):
    run = tmp_path / "fdrc_explain_run2"
    run.mkdir()
    write_jsonl(run / "episodes.jsonl", [sample_fdrc_episode(episode_id="x")])
    store = DashboardStore(tmp_path)
    result = store.explain_metric("fdrc_explain_run2", "some_unknown_metric", track=FDRC_TRACK)
    assert result["supported"] is False
    assert result["label"]


def test_explain_metric_supports_policy_gating_track(tmp_path):
    run = tmp_path / "pg_explain_run"
    run.mkdir()
    episodes = [
        sample_episode(episode_id="p1"),
        sample_episode(
            episode_id="p2",
            scores={"final_pass": 0, "tool_exact_match": 0, "argument_exact_match": 0, "state_match": 0},
            decision="execute",
            failure_types=["POLICY_VIOLATION"],
        ),
    ]
    write_jsonl(run / "episodes.jsonl", episodes)

    store = DashboardStore(tmp_path)
    summary = store.run_summary("pg_explain_run", track="voice_policy_command_gating")
    key = "final_state_correctness"
    displayed = summary["metrics"].get(key)

    result = store.explain_metric("pg_explain_run", key, track="voice_policy_command_gating")
    assert result["supported"] is True
    assert result["formula_vi"]
    assert result["numerator"] == len(result["numerator_episodes"])
    if displayed is None:
        assert result["value"] is None
    else:
        assert abs(result["value"] - displayed) < 1e-9


def test_explain_metric_missing_run_raises(tmp_path):
    store = DashboardStore(tmp_path)
    with pytest.raises(RunNotFound):
        store.explain_metric("does_not_exist", "forbidden_tool_call_rate")


def test_explain_metric_reports_recomputed_value_when_metrics_json_valid_but_stale(tmp_path):
    run = tmp_path / "fdrc_explain_run3"
    run.mkdir()
    episodes = [sample_fdrc_episode(episode_id="a1"), sample_fdrc_episode(episode_id="a2")]
    write_jsonl(run / "episodes.jsonl", episodes)
    # metrics.json with a matching episode_set_hash but a deliberately wrong value
    write_json(run / "metrics.json", metrics_with_metadata(episodes, {"forbidden_tool_call_rate": 0.999}))

    store = DashboardStore(tmp_path)
    result = store.explain_metric("fdrc_explain_run3", "forbidden_tool_call_rate", track=FDRC_TRACK)
    assert result["metric_source"] == "episodes.jsonl"
    assert result["metrics_hash_valid"] is True
    assert result["value"] == result["recomputed_value"]  # headline = evaluator-derived value
    assert result["metrics_json_value"] == 0.999
    assert result["metrics_json_matches_recomputed"] is False
    assert result["value_matches_recomputed"] is True


def test_policy_gating_summary_prefers_recomputed_metrics_over_stale_metrics_json(tmp_path):
    run = tmp_path / "pg_stale_metric_run"
    run.mkdir()
    episodes = [
        sample_episode(
            episode_id="p1",
            policy_gating={"decision_correct": True, "response_honest": True},
        ),
        sample_episode(
            episode_id="p2",
            scores={"final_pass": 0, "tool_exact_match": 0, "argument_exact_match": 0, "state_match": 0},
            policy_gating={"decision_correct": False, "response_honest": True},
        ),
    ]
    write_jsonl(run / "episodes.jsonl", episodes)
    write_json(run / "metrics.json", metrics_with_metadata(episodes, {"policy_compliance_rate": 0.999}))

    summary = DashboardStore(tmp_path).run_summary(
        "pg_stale_metric_run", track="voice_policy_command_gating"
    )

    assert summary["metrics_hash_valid"] is True
    assert summary["metric_source"] == "episodes.jsonl"
    assert summary["metrics"]["policy_compliance_rate"] == 0.5


def test_metric_catalog_includes_plain_meaning_and_result_comment(tmp_path):
    run = tmp_path / "pg_metric_explainability_run"
    run.mkdir()
    episodes = [
        sample_episode(
            episode_id="p1",
            policy_gating={"decision_correct": True, "response_honest": True},
        ),
        sample_episode(
            episode_id="p2",
            scores={"final_pass": 0, "tool_exact_match": 0, "argument_exact_match": 0, "state_match": 0},
            policy_gating={"decision_correct": False, "response_honest": True},
        ),
    ]
    write_jsonl(run / "episodes.jsonl", episodes)

    summary = DashboardStore(tmp_path).run_summary(
        "pg_metric_explainability_run", track="voice_policy_command_gating"
    )
    policy_card = next(
        row for row in summary["metric_catalog"] if row["key"] == "policy_compliance_rate"
    )

    assert "execute, clarify, refuse" in policy_card["plain_meaning"]
    assert "50.0%" in policy_card["result_comment"]
    assert "n=2" in policy_card["result_comment"]

    detail = DashboardStore(tmp_path).explain_metric(
        "pg_metric_explainability_run",
        "policy_compliance_rate",
        track="voice_policy_command_gating",
    )
    assert detail["plain_meaning"] == policy_card["plain_meaning"]
    assert "50.0%" in detail["result_comment"]


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


def test_policy_gating_summary_has_group_and_matrix(tmp_path):
    import json
    import subprocess
    import sys
    from pathlib import Path
    from src.dashboard.service import DashboardStore
    out = tmp_path / "results" / "pg_ref"
    subprocess.run(
        [sys.executable, "-m", "src.run_policy_gating", "--reference-agent",
         "--personas", "vi_north_normal", "--output", str(out)],
        check=True, cwd=Path(__file__).resolve().parents[1],
    )
    store = DashboardStore(tmp_path / "results")
    summary = store.run_summary("pg_ref", track="voice_policy_command_gating")
    assert summary["benchmark_track"] == "voice_policy_command_gating"
    group_ids = {g["id"] for g in summary["metric_groups"]}
    assert "policy_gating" in group_ids
    assert "retention" not in group_ids
    keys = {m["key"] for m in summary["metric_catalog"]}
    assert "policy_compliance_rate" in keys
    assert "forbidden_tool_call_rate" in keys
    assert len(summary["decision_confusion_matrix"]) == 16
    assert summary["state_pairs"]
    # No null cards on the policy tab, and no FDRC-only yield-latency group.
    assert "latency" not in group_ids
    null_cards = [m["key"] for m in summary["metric_catalog"] if m["value"] is None]
    assert null_cards == []


def test_evaluation_view_uses_embedded_snapshot_for_unknown_overlay_id():
    # A v2 run whose speech_overlay_id is NOT in the default overlays file must still
    # evaluate, by using the overlay_snapshot carried on the episode.
    from src.io import load_base_tasks, load_overlays
    from src.runner import reference_episode
    from src.dashboard.service import _evaluation_view

    tasks = load_base_tasks()
    overlay = dict(next(r for r in load_overlays()
                        if r["benchmark_track"] == "full_duplex_repair_to_commit"))
    task = tasks[overlay["base_task_id"]]
    episode = reference_episode(task, overlay, "full_duplex_repair_to_commit", "vi_north_normal")
    episode["run_kind"] = "provider"
    episode["is_reference"] = False
    overlay["speech_overlay_id"] = "fdrc_v2_999_not_in_default_file"
    episode["speech_overlay_id"] = "fdrc_v2_999_not_in_default_file"
    episode["overlay_snapshot"] = overlay

    [row] = _evaluation_view([episode])
    assert "unknown_overlay" not in str(row.get("failure_types", []))
    assert row.get("scores", {}).get("final_pass") is not None
