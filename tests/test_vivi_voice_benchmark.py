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
from src.runner import (
    evaluate_episodes,
    load_or_build_episodes,
    merge_existing_episodes,
    reference_episode,
)
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


def test_fdrc_golden_dataset_balances_modes_accents_and_domains():
    golden = load_overlays("data/jsonl/fdrc_golden_dataset.jsonl")
    tasks = load_base_tasks()
    preflight_validate_assets(tasks, golden, require_mvp_counts=False)
    assert len(golden) == 27
    assert {row["golden_dataset_id"] for row in golden} == {"fdrc_balanced_v1"}
    assert Counter(row["domain"] for row in golden) == {
        "automotive": 9,
        "navigation": 9,
        "media_phone": 9,
    }
    assert Counter(row["accent_region"] for row in golden) == {
        "north": 9,
        "central": 9,
        "south": 9,
    }
    assert Counter(row["repair_mode"] for row in golden) == {
        "entity_repair": 9,
        "slot_repair": 9,
        "cancel_before_commit": 9,
    }


def test_v2_90_dataset_passes_preflight():
    tasks = load_base_tasks()
    overlays = load_overlays("data/jsonl/fdrc_golden_enriched_v2_90.jsonl")
    assert len(overlays) == 90
    preflight_validate_assets(tasks, overlays, require_mvp_counts=False)


def test_legacy_jsonl_paths_resolve_to_data_jsonl():
    assert load_overlays("src/speech_task_overlays.jsonl") == load_overlays(
        "data/jsonl/speech_task_overlays.jsonl"
    )


def test_fdrc_reference_builder_expands_audio_conditions_with_unique_episode_ids():
    tasks = load_base_tasks()
    overlay = next(
        row
        for row in load_overlays()
        if row["benchmark_track"] == "full_duplex_repair_to_commit"
    )
    episodes = load_or_build_episodes(
        None,
        [overlay],
        tasks,
        ["full_duplex_repair_to_commit"],
        ["vi_north_normal"],
        True,
        audio_condition_ids=["clean", "cabin_noise", "interaction_stress"],
    )

    assert [episode["audio_condition_id"] for episode in episodes] == [
        "clean",
        "cabin_noise",
        "interaction_stress",
    ]
    assert len({episode["episode_id"] for episode in episodes}) == 3
    assert all(
        episode["audio_condition_id"] in episode["episode_id"]
        for episode in episodes
    )


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


def test_compute_routes_accepts_array_avoid_and_legacy_string_avoid():
    base_args = {"dest_lat": 21.028, "dest_lng": 105.826, "dest_name": "Ga Cát Linh"}
    assert not validate_tool_schema("compute_routes", {**base_args, "avoid": []})
    assert not validate_tool_schema("compute_routes", {**base_args, "avoid": ["tolls"]})
    assert not validate_tool_schema("compute_routes", {**base_args, "avoid": ""})


def test_compute_routes_accepts_dest_name_without_coords():
    assert not validate_tool_schema(
        "compute_routes",
        {"dest_name": "Vincom Bà Triệu", "routing_mode": "low_traffic"},
    )
    assert validate_tool_schema("compute_routes", {"routing_mode": "fast"})


def test_media_control_accepts_set_volume():
    assert not validate_tool_schema("media_control", {"command": "set_volume", "value": 4})
    assert validate_tool_schema("media_control", {"command": "set_volume"})


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


def test_mock_tool_server_blocks_and_logs_fdrc_cancel_tool_attempt():
    tasks = load_base_tasks()
    overlay = next(row for row in load_overlays() if row["speech_overlay_id"] == "fdrc_cancel_002")
    task = tasks[overlay["base_task_id"]]
    server = MockToolServer("navigation", task, overlay)

    result = server.execute("compute_routes", overlay["forbidden_tool_calls"][0]["args"], t_ms=4600)
    final_state = server.final_state()

    assert result.ok is False
    assert result.content["success"] is False
    assert result.content["error"] == "cancelled_intent_forbids_tool_call"
    assert len(server.tool_call_log) == 1
    assert not any(item.get("success") is True for item in server.tool_results)
    assert final_state["committed_intent"] == "cancel"
    assert final_state["fdrc"]["commit_status"] == "cancel_violation"
    assert final_state["fdrc"]["cancel_attempted_tool_call"] is True
    assert final_state["fdrc"]["cancel_tool_call_count"] == 1
    assert "route" not in final_state.get("navigation", {})


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
    assert result["repair"]["cancel_respected"] is False
    assert result["repair"]["cancel_attempted_tool_call"] is True
    assert result["repair"]["cancel_tool_call_count"] == 1
    assert result["repair"]["cancel_blocked_tool_call_count"] == 0
    assert FailureType.CANCEL_NOT_RESPECTED in result["failure_types"]


def test_fdrc_cancel_fails_when_tool_attempt_is_rejected():
    tasks = load_base_tasks()
    overlay = next(row for row in load_overlays() if row["speech_overlay_id"] == "fdrc_cancel_002")
    task = tasks[overlay["base_task_id"]]
    episode = reference_episode(
        task, overlay, "full_duplex_repair_to_commit", "vi_north_normal"
    )
    episode["tool_calls"] = [{**overlay["forbidden_tool_calls"][0], "t_ms": 4600}]
    episode["tool_results"] = [
        {"success": False, "error": "cancelled_intent_forbids_tool_call"}
    ]
    episode["final_state"] = {"committed_intent": "cancel"}

    result = evaluate_fdrc_episode(episode, overlay, task)

    assert result["scores"]["task_pass"] == 0
    assert result["scores"]["final_pass"] == 0
    assert result["repair"]["cancel_respected"] is False
    assert result["repair"]["cancel_blocked_tool_call_count"] == 1
    assert FailureType.CANCEL_NOT_RESPECTED in result["failure_types"]


def test_fdrc_cancel_passes_when_no_tool_is_attempted():
    tasks = load_base_tasks()
    overlay = next(row for row in load_overlays() if row["speech_overlay_id"] == "fdrc_cancel_001")
    task = tasks[overlay["base_task_id"]]
    episode = reference_episode(
        task, overlay, "full_duplex_repair_to_commit", "vi_north_normal"
    )

    result = evaluate_fdrc_episode(episode, overlay, task)

    assert result["scores"]["final_pass"] == 1
    assert result["repair"]["cancel_respected"] is True
    assert result["repair"]["cancel_attempted_tool_call"] is False
    assert result["repair"]["cancel_tool_call_count"] == 0
    assert FailureType.CANCEL_NOT_RESPECTED not in result["failure_types"]


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


def test_fdrc_provider_allows_helper_tool_when_final_commit_matches_repair():
    tasks = load_base_tasks()
    overlay = next(row for row in load_overlays() if row["speech_overlay_id"] == "fdrc_navigation_005")
    task = tasks[overlay["base_task_id"]]
    expected_call = deepcopy(overlay["expected_tool_calls"][0])
    episode = reference_episode(
        task, overlay, "full_duplex_repair_to_commit", "vi_north_normal"
    )
    episode["is_reference"] = False
    episode["run_kind"] = "provider"
    episode["tool_calls"] = [
        {"tool": "search_places", "args": {"query": "Ga Cát Linh", "max_results": 1}, "t_ms": 4400},
        {**expected_call, "t_ms": 4700},
    ]
    episode["tool_results"] = [{"success": True}, {"success": True}]
    episode["final_state"] = {"committed_intent": "compute_routes"}
    episode["captured_slots"] = {}
    episode["voice_events"] = [
        {"event": "assistant_speech_start", "t_ms": 2600, "source": "observed"},
        {"event": "user_interrupt_start", "t_ms": 3300, "source": "observed"},
        {"event": "repair_audio_start", "t_ms": 3300, "source": "observed"},
        {"event": "assistant_yielded", "t_ms": 3700, "source": "observed"},
        {"event": "repair_transcript_done", "t_ms": 4200, "source": "observed"},
    ]
    episode["normalized_events"] = [
        {"type": "tool_result", "t_ms": 4410, "tool": "search_places"},
        {"type": "tool_result", "t_ms": 4710, "tool": "compute_routes"},
    ]

    result = evaluate_fdrc_episode(episode, overlay, task)

    assert result["scores"]["tool_exact_match"] == 0
    assert result["scores"]["task_pass"] == 1
    assert result["scores"]["final_pass"] == 1
    assert result["repair"]["correction_uptaken"] is True
    assert result["critical_slot_result"]["passed"] is True


def test_fdrc_provider_fails_when_final_commit_destination_is_wrong():
    tasks = load_base_tasks()
    overlay = next(row for row in load_overlays() if row["speech_overlay_id"] == "fdrc_navigation_005")
    task = tasks[overlay["base_task_id"]]
    episode = reference_episode(
        task, overlay, "full_duplex_repair_to_commit", "vi_north_normal"
    )
    episode["is_reference"] = False
    episode["run_kind"] = "provider"
    episode["tool_calls"] = [
        {
            "tool": "compute_routes",
            "args": {"dest_lat": 10.785, "dest_lng": 106.8223, "dest_name": "Linh Đàm"},
            "t_ms": 4700,
        }
    ]
    episode["tool_results"] = [{"success": True}]
    episode["final_state"] = {"committed_intent": "compute_routes"}
    episode["captured_slots"] = {}
    episode["voice_events"] = [
        {"event": "assistant_speech_start", "t_ms": 2600, "source": "observed"},
        {"event": "user_interrupt_start", "t_ms": 3300, "source": "observed"},
        {"event": "repair_audio_start", "t_ms": 3300, "source": "observed"},
        {"event": "assistant_yielded", "t_ms": 3700, "source": "observed"},
        {"event": "repair_transcript_done", "t_ms": 4200, "source": "observed"},
    ]
    episode["normalized_events"] = [
        {"type": "tool_result", "t_ms": 4710, "tool": "compute_routes"},
    ]

    result = evaluate_fdrc_episode(episode, overlay, task)

    assert result["scores"]["final_pass"] == 0
    assert FailureType.REPAIR_INTENT_MISMATCH in result["failure_types"]
    assert FailureType.CORRECTION_NOT_UPTAKEN not in result["failure_types"]
    assert result["primary_failure_type"] == str(FailureType.REPAIR_INTENT_MISMATCH)
    assert result["critical_slot_result"]["passed"] is False


def test_fdrc_provider_flags_cross_episode_repair_intent_mismatch():
    tasks = load_base_tasks()
    overlay = deepcopy(
        next(row for row in load_overlays() if row["speech_overlay_id"] == "fdrc_navigation_005")
    )
    task = tasks[overlay["base_task_id"]]
    initial_dest = "C\u00f4ng vi\u00ean Th\u1ed1ng Nh\u1ea5t"
    repaired_dest = "C\u00f4ng vi\u00ean Y\u00ean S\u1edf"
    leaked_dest = "C\u00f4ng vi\u00ean G\u00f2 V\u1ea5p"
    overlay.update(
        {
            "initial_spoken_utterance": f"D\u1eabn t\u00f4i \u0111\u1ebfn {initial_dest}.",
            "repair_utterance": f"Kh\u00f4ng, \u0111\u1ebfn {repaired_dest} c\u01a1.",
            "initial_intent": {
                "tool": "compute_routes",
                "args": {
                    "dest_name": initial_dest,
                    "routing_mode": "fast",
                    "dest_lat": 21.011,
                    "dest_lng": 105.843,
                },
            },
            "expected_critical_slots": {
                "dest_name": repaired_dest,
                "routing_mode": "fast",
            },
            "forbidden_tool_calls": [
                {
                    "tool": "compute_routes",
                    "args": {
                        "dest_name": initial_dest,
                        "routing_mode": "fast",
                        "dest_lat": 21.011,
                        "dest_lng": 105.843,
                    },
                }
            ],
            "expected_tool_calls": [
                {
                    "tool": "compute_routes",
                    "args": {
                        "dest_name": repaired_dest,
                        "routing_mode": "fast",
                        "dest_lat": 20.959,
                        "dest_lng": 105.831,
                    },
                }
            ],
        }
    )
    episode = reference_episode(
        task, overlay, "full_duplex_repair_to_commit", "vi_north_normal"
    )
    episode["is_reference"] = False
    episode["run_kind"] = "provider"
    episode["tool_calls"] = [
        {
            "tool": "compute_routes",
            "args": {
                "dest_name": leaked_dest,
                "routing_mode": "fast",
                "origin_lat": 10.762622,
                "origin_lng": 106.660172,
                "dest_lat": 10.8171,
                "dest_lng": 106.7051,
            },
            "t_ms": 8947,
        }
    ]
    episode["tool_results"] = [{"success": True}]
    episode["final_state"] = {"committed_intent": "compute_routes"}
    episode["captured_slots"] = {}
    episode["voice_events"] = [
        {"event": "assistant_speech_start", "t_ms": 3023, "source": "observed"},
        {"event": "user_interrupt_start", "t_ms": 4462, "source": "observed"},
        {"event": "repair_audio_start", "t_ms": 4462, "source": "observed"},
        {"event": "assistant_yielded", "t_ms": 3724, "source": "observed"},
        {"event": "repair_transcript_done", "t_ms": 7142, "source": "observed"},
    ]
    episode["normalized_events"] = [
        {"type": "tool_result", "t_ms": 8957, "tool": "compute_routes"},
    ]

    result = evaluate_fdrc_episode(episode, overlay, task)

    assert result["scores"]["final_pass"] == 0
    assert FailureType.REPAIR_INTENT_MISMATCH in result["failure_types"]
    assert FailureType.CORRECTION_NOT_UPTAKEN not in result["failure_types"]
    assert result["repair"]["repair_intent_mismatch"] is True
    assert result["captured_slots"]["dest_name"] == leaked_dest
    assert result["critical_slot_result"]["per_slot"]["dest_name"] is False


def test_evaluate_episodes_embeds_overlay_snapshot():
    tasks = load_base_tasks()
    overlay = next(r for r in load_overlays() if r["benchmark_track"] == "full_duplex_repair_to_commit")
    task = tasks[overlay["base_task_id"]]
    episode = reference_episode(task, overlay, "full_duplex_repair_to_commit", "vi_north_normal")
    [evaluated] = evaluate_episodes([episode], [overlay], tasks, evaluate_fdrc_episode)
    assert evaluated["overlay_snapshot"]["speech_overlay_id"] == overlay["speech_overlay_id"]
    assert evaluated["overlay_snapshot"]["expected_tool_calls"] == overlay.get("expected_tool_calls", [])


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


def test_non_strict_schema_does_not_force_optional_fields():
    # Realtime/Gemini run non-strict: optional fields must NOT appear in `required`,
    # so the model is not forced to emit (and mis-type) media_control.value /
    # compute_routes.avoid. Required stays minimal and truthful.
    from src.tools.vivi_tool_schema import tool_to_openai_schema

    media = tool_to_openai_schema("media_control", strict=False)
    assert media["parameters"]["required"] == ["command"]
    assert "value" in media["parameters"]["properties"]
    assert media["parameters"]["properties"]["value"]["type"] == "integer"  # not nullable
    assert "strict" not in media

    routes = tool_to_openai_schema("compute_routes", strict=False)
    # Optional fields stay OUT of `required`. Do NOT assert the exact required set —
    # a later phase makes compute_routes coords optional. `avoid` is an array.
    assert "avoid" not in routes["parameters"]["required"]
    assert "routing_mode" not in routes["parameters"]["required"]
    assert routes["parameters"]["properties"]["avoid"]["type"] == "array"


def test_strict_schema_unchanged_default_behavior():
    from src.tools.vivi_tool_schema import tool_to_openai_schema

    media = tool_to_openai_schema("media_control")  # default strict=True
    # strict mode keeps the all-required + nullable convention
    assert "value" in media["parameters"]["required"]
    assert media["strict"] is True
    assert media["parameters"]["properties"]["value"]["type"] == ["integer", "null"]


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


def test_fdrc_prompt_has_hard_cancel_and_repair_examples():
    from src.adapters.prompts import build_system_prompt

    tasks = load_base_tasks()
    overlay = next(r for r in load_overlays()
                   if r["benchmark_track"] == "full_duplex_repair_to_commit")
    task = tasks[overlay["base_task_id"]]
    prompt = build_system_prompt(
        task=task, overlay=overlay, mode="full_duplex_repair_to_commit",
        tool_names=["drive_system"],
    )
    # Hard cancel: an explicit "do not call ANY tool" rule, plus worked examples.
    assert "hủy" in prompt and "KHÔNG gọi" in prompt
    assert "Ví dụ" in prompt          # at least one worked example block
    assert "Eco" in prompt or "eco" in prompt  # entity-repair example present
