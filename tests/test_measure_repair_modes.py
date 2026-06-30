from __future__ import annotations


def test_repair_mode_breakdown_counts_pass_by_mode():
    from scripts.measure_repair_modes import repair_mode_breakdown

    episodes = [
        {
            "overlay_snapshot": {"repair_mode": "cancel_before_commit"},
            "scores": {"final_pass": 1},
        },
        {
            "overlay_snapshot": {"repair_mode": "cancel_before_commit"},
            "scores": {"final_pass": 0},
        },
        {
            "overlay_snapshot": {"repair_mode": "entity_repair"},
            "scores": {"final_pass": 1},
        },
    ]
    out = repair_mode_breakdown(episodes)
    assert out["cancel_before_commit"] == {"pass": 1, "total": 2}
    assert out["entity_repair"] == {"pass": 1, "total": 1}
