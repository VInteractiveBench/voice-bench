"""Integration tests for the live/replay user-simulator FDRC path.

Uses a fake realtime adapter and a fake audio cache so no network/TTS is needed. The
simulator's LLM driver is stubbed by monkeypatching the module-level default.
"""
from __future__ import annotations

import asyncio

import numpy as np
import pytest

import src.orchestrator.full_duplex_orchestrator as orch
import src.orchestrator.user_simulator as us


class FakeAdapter:
    """Emits a scripted agent response (starts speaking + a wrong tool_call), then ends."""

    def __init__(self) -> None:
        self._started = 0.0
        self.audio_chunks: list[bytes] = []
        self.committed = 0
        self.cancelled = 0

    async def start_session(self, *, system_prompt, tools) -> None:
        self._events = [
            {"type": "assistant_speech_start", "t_ms": 80},
            {"type": "assistant_text_delta", "t_ms": 120, "text": "Đang chỉnh ghế lái"},
            {"type": "tool_call", "t_ms": 160, "tool": "climate_control",
             "args": {"device": "seat", "position": "driver"}, "call_id": "c1"},
        ]

    async def send_audio_chunk(self, audio_bytes, timestamp_ms) -> None:
        self.audio_chunks.append(audio_bytes)

    async def commit_audio_turn(self) -> None:
        self.committed += 1

    async def cancel_response(self) -> None:
        self.cancelled += 1

    async def send_tool_result(self, call_id, result) -> None:
        pass

    async def receive_events(self):
        for event in self._events:
            await asyncio.sleep(0.02)
            yield event
        # keep the stream alive briefly so the monitor can act, then end
        await asyncio.sleep(0.05)

    async def close(self) -> None:
        pass


class FakeCache:
    def __init__(self) -> None:
        self.requests: list[tuple] = []

    def get_or_build(self, text, accent, speed, condition):
        self.requests.append((text, accent, speed, condition))
        return np.zeros(2400, dtype=np.float32)  # 0.1 s @ 24 kHz


def _overlay() -> dict:
    return {
        "speech_overlay_id": "fdrc_sim_001",
        "benchmark_track": "full_duplex_repair_to_commit",
        "domain": "automotive",
        "initial_spoken_utterance": "Bật điều hòa ghế lái",
        "repair_utterance": "Không, ghế phụ",
        "expected_final_state": {"committed_intent": "fdrc_sim_001"},
        "voice_timeline": [{"event": "user_interrupt_start", "t_ms": 2000}],
    }


def _task() -> dict:
    return {"id": "base_sim", "domain": "automotive", "initial_state": {"committed_intent": None}}


@pytest.fixture
def patched(monkeypatch):
    cache = FakeCache()
    monkeypatch.setattr(orch, "build_adapter", lambda agent, model: FakeAdapter())
    monkeypatch.setattr(orch, "_get_audio_cache", lambda: cache)
    return cache


def _run(simulator_mode, trace_dir, llm):
    return asyncio.run(
        orch.run_agent_episode(
            agent="openai_realtime",
            model="fake-rt",
            task=_task(),
            overlay=_overlay(),
            mode="full_duplex_repair_to_commit",
            persona="vi_north_normal",
            fdrc_yield_mode="native_yield",
            audio_condition_id="interaction_stress",
            simulator_mode=simulator_mode,
            simulator_model="stub-sim",
            sim_trace_dir=str(trace_dir),
        )
    )


def test_live_simulator_barges_in_and_records_trace(patched, tmp_path, monkeypatch):
    calls = {"n": 0}

    async def stub_llm(system_prompt, user_prompt, model):
        calls["n"] += 1
        return {"action": "bargein", "utterance": "Ghế phụ chứ không phải ghế lái"}

    monkeypatch.setattr(us, "_openai_llm_driver", stub_llm)

    episode = _run("live", tmp_path, stub_llm)

    # The simulator opened, then barged in: there must be an overlap marker.
    overlap = [
        e for e in episode["normalized_events"]
        if e.get("type") == "user_audio_chunk_sent" and e.get("overlap")
    ]
    assert overlap, "expected a barge-in overlap marker"
    assert calls["n"] >= 1
    # Trace was recorded with the dynamic repair utterance.
    from src.orchestrator.user_simulator import build_scenario, load_trace

    trace = load_trace(tmp_path, build_scenario(_overlay(), _task()), "vi_north_normal", "stub-sim")
    assert trace is not None
    assert trace.opening == "Bật điều hòa ghế lái"
    assert trace.repair_text == "Ghế phụ chứ không phải ghế lái"
    assert trace.barge_in_t_ms is not None


def test_replay_uses_trace_without_calling_llm(patched, tmp_path, monkeypatch):
    # First, a live run to record a trace.
    async def stub_llm(system_prompt, user_prompt, model):
        return {"action": "bargein", "utterance": "Ghế phụ"}

    monkeypatch.setattr(us, "_openai_llm_driver", stub_llm)
    _run("live", tmp_path, stub_llm)

    # Now replay: the LLM must not be called at all.
    calls = {"n": 0}

    async def forbidden_llm(system_prompt, user_prompt, model):
        calls["n"] += 1
        raise AssertionError("replay must not call the simulator LLM")

    monkeypatch.setattr(us, "_openai_llm_driver", forbidden_llm)
    episode = _run("replay", tmp_path, forbidden_llm)

    assert calls["n"] == 0
    overlap = [
        e for e in episode["normalized_events"]
        if e.get("type") == "user_audio_chunk_sent" and e.get("overlap")
    ]
    assert overlap, "replay should reproduce the barge-in overlap marker"
    # Replay sourced the repair text from the trace.
    assert "Ghế phụ" in episode["user_transcript"]


def test_off_mode_is_unchanged_scripted_path(patched, tmp_path, monkeypatch):
    # off mode must not touch the simulator LLM and must use overlay utterances.
    async def forbidden_llm(system_prompt, user_prompt, model):
        raise AssertionError("off mode must not call the simulator LLM")

    monkeypatch.setattr(us, "_openai_llm_driver", forbidden_llm)
    episode = _run("off", tmp_path, forbidden_llm)

    assert "Bật điều hòa ghế lái" in episode["user_transcript"]
    assert "Không, ghế phụ" in episode["user_transcript"]
