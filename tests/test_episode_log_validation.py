"""A model emitting a schema-invalid tool ARGUMENT is a task failure, not an
invalid episode log. validate_episode_log must gate on structural log integrity
only, so such episodes stay valid-but-failed (counted in the validity denominator)."""
from __future__ import annotations

from src.io import load_base_tasks, load_overlays
from src.runner import reference_episode
from src.schema import validate_episode_log


def _fdrc_episode():
    tasks = load_base_tasks()
    overlay = next(r for r in load_overlays() if r["speech_overlay_id"] == "fdrc_vehicle_001")
    task = tasks[overlay["base_task_id"]]
    episode = reference_episode(task, overlay, "full_duplex_repair_to_commit", "vi_north_normal")
    return episode, overlay, task


def test_model_tool_arg_error_does_not_invalidate_log():
    episode, overlay, task = _fdrc_episode()
    # structurally valid call, but a schema-invalid argument value (model failure)
    episode["tool_calls"] = [
        {"tool": "climate_control", "args": {"device": "temp", "value": "on"}, "t_ms": 4600}
    ]
    episode["tool_results"] = [{"success": False}]
    issues = validate_episode_log(episode, overlay, task)
    arg_issues = [i for i in issues if ".args" in i["field"]]
    assert arg_issues == [], arg_issues


def test_structurally_broken_tool_call_still_invalidates_log():
    episode, overlay, task = _fdrc_episode()
    episode["tool_calls"] = ["not-a-dict"]
    episode["tool_results"] = [{"success": True}]
    issues = validate_episode_log(episode, overlay, task)
    assert any(i["field"].startswith("episode.tool_calls[0]") for i in issues), issues


def test_tool_call_missing_tool_name_still_invalidates_log():
    episode, overlay, task = _fdrc_episode()
    episode["tool_calls"] = [{"args": {"device": "temp"}, "t_ms": 4600}]
    episode["tool_results"] = [{"success": True}]
    issues = validate_episode_log(episode, overlay, task)
    assert any(i["field"] == "episode.tool_calls[0].tool" for i in issues), issues