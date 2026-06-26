from __future__ import annotations

import pytest


def test_run_fdrc_default_overlays_is_v2_90(monkeypatch, tmp_path):
    import run_fdrc

    captured = {}

    monkeypatch.setattr(run_fdrc, "load_benchmark_env", lambda: None)
    monkeypatch.setattr(run_fdrc, "load_base_tasks", lambda: {})
    monkeypatch.setattr(run_fdrc, "load_overlays", lambda path: [])
    monkeypatch.setattr(
        run_fdrc,
        "preflight_validate_assets",
        lambda tasks, overlays, *, require_mvp_counts: captured.update(
            require_mvp_counts=require_mvp_counts
        ),
    )

    def fake_select_overlays(path, track, domains):
        captured["overlays"] = path
        raise RuntimeError("stop after parse")

    monkeypatch.setattr(run_fdrc, "select_overlays", fake_select_overlays)
    monkeypatch.setattr(
        "sys.argv",
        ["run_fdrc.py", "--reference-agent", "--output", str(tmp_path / "out")],
    )

    with pytest.raises(RuntimeError, match="stop after parse"):
        run_fdrc.main()

    assert captured["overlays"] == "fdrc_golden_enriched_v2_90.jsonl"
    assert captured["require_mvp_counts"] is False
