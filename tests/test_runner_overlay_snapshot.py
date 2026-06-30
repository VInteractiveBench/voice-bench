from __future__ import annotations

from src.evaluator.fdrc_evaluator import evaluate_fdrc_episode
from src.io import load_base_tasks, load_overlays
from src.runner import evaluate_episodes, reference_episode


def test_evaluate_episodes_embeds_overlay_snapshot_on_invalid_episode():
    tasks = load_base_tasks()
    overlay = next(
        row
        for row in load_overlays()
        if row["benchmark_track"] == "full_duplex_repair_to_commit"
    )
    task = tasks[overlay["base_task_id"]]
    episode = reference_episode(
        task, overlay, "full_duplex_repair_to_commit", "vi_north_normal"
    )
    del episode["final_state"]

    [evaluated] = evaluate_episodes([episode], [overlay], tasks, evaluate_fdrc_episode)

    assert evaluated["scores"]["final_pass"] == 0
    assert evaluated["overlay_snapshot"]["speech_overlay_id"] == overlay["speech_overlay_id"]
