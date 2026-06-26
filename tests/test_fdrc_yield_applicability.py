"""#3a: yield-latency and the speaking-before-interrupt policy check must be
conditional on a REAL barge-in. If the assistant had not started speaking when the
scripted interrupt fired (e.g. a slow-responding provider), there is nothing to
interrupt — yield latency is N/A, not a failure, and it is not a policy violation."""
from __future__ import annotations

from src.io import load_base_tasks, load_overlays
from src.runner import reference_episode
from src.evaluator.failure_taxonomy import FailureType
from src.evaluator.fdrc_evaluator import evaluate_fdrc_episode


def _provider_episode(*, speech_start_ms: int, yielded_ms: int):
    """A provider (non-reference) FDRC episode with observed voice events. The
    assistant speaks at `speech_start_ms`; the scripted interrupt is at 3300ms."""
    tasks = load_base_tasks()
    overlay = next(r for r in load_overlays() if r["speech_overlay_id"] == "fdrc_vehicle_001")
    task = tasks[overlay["base_task_id"]]
    episode = reference_episode(task, overlay, "full_duplex_repair_to_commit", "vi_north_normal")
    episode["is_reference"] = False
    episode["run_kind"] = "provider"
    # Make the committed tool call land after the repair so it isn't an early commit.
    for call in episode["tool_calls"]:
        call["t_ms"] = 13000
    episode["voice_events"] = [
        {"event": "assistant_speech_start", "t_ms": speech_start_ms, "source": "observed"},
        {"event": "user_interrupt_start", "t_ms": 3300, "source": "observed"},
        {"event": "repair_audio_start", "t_ms": 3400, "source": "observed"},
        {"event": "repair_transcript_done", "t_ms": 3600, "source": "observed"},
        {"event": "assistant_yielded", "t_ms": yielded_ms, "source": "observed"},
        {"event": "assistant_speech_stop", "t_ms": yielded_ms, "source": "observed"},
    ]
    episode["normalized_events"] = [
        {"type": "user_audio_chunk_sent", "t_ms": 0},
        {"type": "repair_transcript_done", "t_ms": 3600, "text": "đặt 24 độ"},
        {"type": "tool_result", "t_ms": 13000},
    ]
    return episode, overlay, task


def test_no_real_bargein_does_not_fail_yield_or_policy():
    # Assistant starts speaking at 10s, long after the 3.3s interrupt: no barge-in.
    episode, overlay, task = _provider_episode(speech_start_ms=10000, yielded_ms=12000)
    result = evaluate_fdrc_episode(episode, overlay, task)
    assert FailureType.YIELD_LATENCY_TOO_HIGH not in result["failure_types"]
    assert FailureType.POLICY_VIOLATION not in result["failure_types"]
    # yield latency is recorded but marked not-applicable for scoring
    assert result["repair"]["assistant_speaking_before_interrupt"] is False


def test_real_bargein_with_slow_yield_still_fails_yield():
    # Assistant speaking at 2s (before interrupt) but yields only at 8s: real barge-in,
    # genuinely too slow -> must still fail.
    episode, overlay, task = _provider_episode(speech_start_ms=2000, yielded_ms=8000)
    result = evaluate_fdrc_episode(episode, overlay, task)
    assert FailureType.YIELD_LATENCY_TOO_HIGH in result["failure_types"]
    assert result["repair"]["assistant_speaking_before_interrupt"] is True


def test_contract_reports_yield_over_applicable_rows_only():
    from src.evaluator.fdrc_contract import summarize_fdrc_contract

    def row(applicable, yld, fail):
        return {
            "benchmark_track": "full_duplex_repair_to_commit",
            "scores": {"final_pass": 0, "state_match": 0},
            "repair": {"final_intent": "drive_system"},
            "latency": {"yield_latency_ms": yld, "yield_applicable": applicable},
            "failure_types": (["YIELD_LATENCY_TOO_HIGH"] if fail else []),
        }

    rows = [
        row(False, 3392, False),  # not applicable — excluded from percentiles
        row(False, 5401, False),
        row(True, 650, False),    # applicable, passes
        row(True, 1200, True),    # applicable, too slow
    ]
    m = summarize_fdrc_contract(rows)
    assert m["yield_applicable_count"] == 2
    assert m["yield_latency_p95_ms"] == 1200.0
    # pass-rate over applicable rows only: 1 of 2 passed
    assert m["yield_latency_pass_rate"] == 0.5
