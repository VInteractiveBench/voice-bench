from collections import Counter
from copy import deepcopy
import json
from pathlib import Path

import pytest

from src.evaluator.failure_taxonomy import FailureType
from src.evaluator.fdrc_evaluator import evaluate_fdrc_episode
from src.evaluator.policy_gating_evaluator import evaluate_policy_gating_episode
from src.evaluator.tool_schema_validator import validate_tool_schema
from src.evaluator.tool_scope_validator import validate_tool_scope
from src.io import load_base_tasks, load_overlays
from src.runner import evaluate_episodes, merge_existing_episodes, reference_episode
from src.schema import preflight_validate_assets
from src.tools import MockToolServer, get_openai_tool_schemas


def test_mvp_overlay_scope_and_distribution():
    overlays = load_overlays()
    tracks = Counter(row["benchmark_track"] for row in overlays)
    fdrc_categories = Counter(
        row["speech_overlay_id"].split("_")[1]
        for row in overlays
        if row["benchmark_track"] == "full_duplex_repair_to_commit"
    )
    assert tracks["full_duplex_repair_to_commit"] == 30
    assert tracks["voice_policy_command_gating"] >= 24
    assert "text_to_voice_retention" not in tracks
    assert fdrc_categories == {
        "navigation": 8,
        "phone": 8,
        "vehicle": 8,
        "media": 4,
        "cancel": 2,
    }


def test_asset_preflight_accepts_committed_mvp_assets():
    preflight_validate_assets(load_base_tasks(), load_overlays())


def test_asset_preflight_rejects_malformed_fdrc_timeline():
    tasks = load_base_tasks()
    overlays = deepcopy(load_overlays())
    broken = next(row for row in overlays if row["benchmark_track"] == "full_duplex_repair_to_commit")
    broken["voice_timeline"][1]["t_ms"] = -1
    try:
        preflight_validate_assets(tasks, overlays)
    except ValueError as exc:
        assert "negative_time" in str(exc)
    else:
        raise AssertionError("Malformed FDRC timeline passed preflight")


def test_tool_scope_distinguishes_excluded_from_hallucinated():
    assert validate_tool_scope("weather") == FailureType.OUT_OF_SCOPE_TOOL_CALL
    assert validate_tool_scope("call_start") == FailureType.TOOL_NOT_IN_WHITELIST
    assert validate_tool_scope("phone_manager") is None


def _policy_execute_overlay():
    return next(
        row
        for row in load_overlays()
        if row["benchmark_track"] == "voice_policy_command_gating"
        and row["task_type"] == "execute_allowed"
    )


def test_episode_evaluator_preserves_scope_failure_classification():
    tasks = load_base_tasks()
    overlay = _policy_execute_overlay()
    task = tasks[overlay["base_task_id"]]
    episode = reference_episode(task, overlay, "voice_policy_gating", "vi_north_normal")
    episode["tool_calls"] = [{"tool": "weather", "args": {"location": "Hà Nội"}}]
    episode["tool_results"] = [{"success": True}]
    result = evaluate_policy_gating_episode(episode, overlay, task)
    assert result["primary_failure_type"] == FailureType.OUT_OF_SCOPE_TOOL_CALL
    assert FailureType.TOOL_NOT_IN_WHITELIST not in result["failure_types"]


def test_runner_marks_malformed_episode_as_validation_error():
    tasks = load_base_tasks()
    overlay = _policy_execute_overlay()
    task = tasks[overlay["base_task_id"]]
    episode = reference_episode(task, overlay, "voice_policy_gating", "vi_north_normal")
    del episode["final_state"]
    result = evaluate_episodes([episode], [overlay], tasks, evaluate_policy_gating_episode)[0]
    assert result["scores"]["final_pass"] == 0
    assert FailureType.VALIDATION_ERROR in result["failure_types"]


def test_runner_marks_unknown_overlay_as_validation_error():
    tasks = load_base_tasks()
    overlay = _policy_execute_overlay()
    task = tasks[overlay["base_task_id"]]
    episode = reference_episode(task, overlay, "voice_policy_gating", "vi_north_normal")
    episode["speech_overlay_id"] = "does_not_exist"
    result = evaluate_episodes([episode], [overlay], tasks, evaluate_policy_gating_episode)[0]
    assert result["scores"]["final_pass"] == 0
    assert FailureType.VALIDATION_ERROR in result["failure_types"]


def test_schema_validator_enforces_conditional_arguments():
    assert validate_tool_schema(
        "audio_control", {"device": "entertainment", "action": "set"}
    )
    assert not validate_tool_schema(
        "audio_control", {"device": "entertainment", "action": "set", "level": 40}
    )
    assert validate_tool_schema(
        "climate_control", {"device": "temp", "value": "31"}
    )


def test_openai_tool_schemas_are_strict_and_domain_scoped():
    schemas = get_openai_tool_schemas("navigation")
    names = {schema["name"] for schema in schemas}
    assert names == {
        "search_places",
        "compute_routes",
        "map_control",
        "saved_places",
        "check_traffic",
    }
    assert all(schema["strict"] is True for schema in schemas)
    assert all(
        schema["parameters"]["additionalProperties"] is False for schema in schemas
    )


def test_mock_tool_server_executes_and_owns_final_state():
    tasks = load_base_tasks()
    task = tasks["navigation_base_010"]
    server = MockToolServer("navigation", task)
    result = server.execute("map_control", {"action": "stop_navigation"}, t_ms=4300)
    assert result.ok is True
    assert server.final_state()["committed_intent"] == "navigation_base_010"
    bad = server.execute("weather", {"location": "Hà Nội"})
    assert bad.ok is False
    assert bad.validation_errors[0]["reason"] == "OUT_OF_SCOPE_TOOL_CALL"


def test_policy_missing_required_communication_fails():
    tasks = load_base_tasks()
    overlay = _policy_execute_overlay()
    task = tasks[overlay["base_task_id"]]
    episode = reference_episode(task, overlay, "voice_policy_gating", "vi_north_normal")
    episode["assistant_transcript"] = []
    result = evaluate_policy_gating_episode(episode, overlay, task)
    assert result["scores"]["final_pass"] == 0
    assert FailureType.FABRICATED_SUCCESS in result["failure_types"]


def test_fdrc_detects_forbidden_old_intent_and_yield_failure():
    tasks = load_base_tasks()
    overlay = next(
        row
        for row in load_overlays()
        if row["speech_overlay_id"] == "fdrc_vehicle_001"
    )
    task = tasks[overlay["base_task_id"]]
    episode = reference_episode(
        task, overlay, "full_duplex_repair_to_commit", "vi_north_normal"
    )
    episode["tool_calls"].append({**overlay["forbidden_tool_calls"][0], "t_ms": 4500})
    episode["voice_events"] = [
        event for event in episode["voice_events"] if event["event"] != "assistant_yielded"
    ]
    result = evaluate_fdrc_episode(episode, overlay, task)
    assert result["scores"]["final_pass"] == 0
    assert FailureType.FORBIDDEN_TOOL_CALL in result["failure_types"]
    assert FailureType.YIELD_LATENCY_TOO_HIGH in result["failure_types"]


def test_fdrc_detects_early_commit_as_policy_violation():
    tasks = load_base_tasks()
    overlay = next(row for row in load_overlays() if row["speech_overlay_id"] == "fdrc_vehicle_001")
    task = tasks[overlay["base_task_id"]]
    episode = reference_episode(
        task, overlay, "full_duplex_repair_to_commit", "vi_north_normal"
    )
    episode["tool_calls"][0]["t_ms"] = 3000
    result = evaluate_fdrc_episode(episode, overlay, task)
    assert result["scores"]["final_pass"] == 0
    assert FailureType.POLICY_VIOLATION in result["failure_types"]


def test_fdrc_cancel_fails_when_any_tool_commits():
    tasks = load_base_tasks()
    overlay = next(row for row in load_overlays() if row["speech_overlay_id"] == "fdrc_cancel_001")
    task = tasks[overlay["base_task_id"]]
    episode = reference_episode(
        task, overlay, "full_duplex_repair_to_commit", "vi_north_normal"
    )
    episode["tool_calls"] = [{**overlay["forbidden_tool_calls"][0], "t_ms": 4600}]
    episode["tool_results"] = [{"success": True}]
    result = evaluate_fdrc_episode(episode, overlay, task)
    assert result["scores"]["final_pass"] == 0
    assert FailureType.CANCEL_NOT_RESPECTED in result["failure_types"]


def test_fdrc_detects_duplicate_final_commit():
    tasks = load_base_tasks()
    overlay = next(row for row in load_overlays() if row["speech_overlay_id"] == "fdrc_vehicle_001")
    task = tasks[overlay["base_task_id"]]
    episode = reference_episode(
        task, overlay, "full_duplex_repair_to_commit", "vi_north_normal"
    )
    episode["tool_calls"].append(deepcopy(episode["tool_calls"][0]))
    episode["tool_calls"][1]["t_ms"] = 4800
    episode["tool_results"].append({"success": True})
    result = evaluate_fdrc_episode(episode, overlay, task)
    assert result["scores"]["final_pass"] == 0
    assert result["repair"]["duplicate_final_commit"] is True
    assert FailureType.POLICY_VIOLATION in result["failure_types"]


def test_fdrc_detects_continued_old_confirmation():
    tasks = load_base_tasks()
    overlay = next(row for row in load_overlays() if row["speech_overlay_id"] == "fdrc_vehicle_001")
    task = tasks[overlay["base_task_id"]]
    episode = reference_episode(
        task, overlay, "full_duplex_repair_to_commit", "vi_north_normal"
    )
    episode["voice_events"].append(
        {"event": "assistant_continued_old_confirmation", "t_ms": 3600}
    )
    result = evaluate_fdrc_episode(episode, overlay, task)
    assert result["scores"]["final_pass"] == 0
    assert FailureType.POLICY_VIOLATION in result["failure_types"]


def test_fdrc_provider_requires_observed_timing_events():
    tasks = load_base_tasks()
    overlay = next(row for row in load_overlays() if row["speech_overlay_id"] == "fdrc_vehicle_001")
    task = tasks[overlay["base_task_id"]]
    episode = reference_episode(
        task, overlay, "full_duplex_repair_to_commit", "vi_north_normal"
    )
    episode["is_reference"] = False
    episode["run_kind"] = "provider"

    result = evaluate_fdrc_episode(episode, overlay, task)
    assert result["scores"]["final_pass"] == 0
    assert FailureType.MISSING_OBSERVED_EVENT in result["failure_types"]
    assert "assistant_speech_start" in result["repair"]["missing_observed_events"]


def test_fdrc_provider_passes_with_observed_repair_to_commit_lifecycle():
    tasks = load_base_tasks()
    overlay = next(row for row in load_overlays() if row["speech_overlay_id"] == "fdrc_vehicle_001")
    task = tasks[overlay["base_task_id"]]
    episode = reference_episode(
        task, overlay, "full_duplex_repair_to_commit", "vi_north_normal"
    )
    episode["is_reference"] = False
    episode["run_kind"] = "provider"
    episode["voice_events"] = [
        {"event": "assistant_speech_start", "t_ms": 2600, "source": "observed"},
        {"event": "user_interrupt_start", "t_ms": 3300, "source": "observed"},
        {"event": "repair_audio_start", "t_ms": 3300, "source": "observed"},
        {"event": "assistant_yielded", "t_ms": 3700, "source": "observed"},
        {"event": "repair_transcript_done", "t_ms": 4200, "source": "observed"},
    ]
    episode["normalized_events"] = [
        {"type": "tool_result", "t_ms": 4610, "tool": episode["tool_calls"][0]["tool"]}
    ]

    result = evaluate_fdrc_episode(episode, overlay, task)
    assert result["scores"]["final_pass"] == 1
    assert result["latency"]["yield_latency_ms"] == 400


def test_merge_existing_episodes_deduplicates_by_episode_id(tmp_path):
    task = load_base_tasks()["navigation_base_010"]
    overlay = next(row for row in load_overlays() if row["base_task_id"] == "navigation_base_010")
    episode = reference_episode(task, overlay, "full_duplex_repair_to_commit", "vi_north_normal")
    output = tmp_path / "results"
    output.mkdir()
    (output / "episodes.jsonl").write_text(
        json.dumps(episode, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    updated = deepcopy(episode)
    updated["scores"] = {"final_pass": 0}
    merged = merge_existing_episodes(str(output), [updated])
    assert len(merged) == 1
    assert merged[0]["scores"]["final_pass"] == 0


def test_all_overlay_tools_are_official_and_in_scope():
    tasks = load_base_tasks()
    for task in tasks.values():
        for tool_call in task["expected_tool_calls"]:
            assert validate_tool_scope(tool_call["tool"]) is None
            assert not validate_tool_schema(tool_call["tool"], tool_call["args"])


def test_automotive_manifest_preserves_domain_expected_actions():
    manifest_path = Path("data/tau2/domains/automotive/tasks.json")
    if not manifest_path.exists():
        pytest.skip("Automotive tau2 source fixture is not present in this checkout")
    source = {
        row["id"]: row
        for row in json.loads(
            manifest_path.read_text(encoding="utf-8")
        )
    }
    for task in load_base_tasks().values():
        if task["domain"] != "automotive":
            continue
        source_calls = [
            {"tool": action["name"], "args": action["arguments"]}
            for action in source[task["id"]]["evaluation_criteria"]["actions"]
        ]
        assert task["expected_tool_calls"] == source_calls
    for overlay in load_overlays():
        for tool_call in overlay.get("expected_tool_calls", []):
            assert validate_tool_scope(tool_call["tool"]) is None
            assert not validate_tool_schema(tool_call["tool"], tool_call["args"])
