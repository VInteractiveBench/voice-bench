from __future__ import annotations

import asyncio

import pytest

from src.orchestrator.user_simulator import (
    Action,
    Scenario,
    SimTrace,
    UserSimulator,
    build_scenario,
    load_trace,
    save_trace,
)


def _scenario() -> Scenario:
    return Scenario(
        overlay_id="fdrc_001",
        domain="automotive",
        opening_intent="Bật điều hòa ghế lái",
        true_goal="Không, ghế phụ chứ không phải ghế lái",
        expected_final_state={"committed_intent": "fdrc_001"},
    )


class _StubLLM:
    """Records calls and returns scripted decisions in order."""

    def __init__(self, decisions: list[dict]) -> None:
        self.decisions = list(decisions)
        self.calls: list[tuple[str, str, str]] = []

    async def __call__(self, system_prompt: str, user_prompt: str, model: str) -> dict:
        self.calls.append((system_prompt, user_prompt, model))
        return self.decisions.pop(0) if self.decisions else {"action": "listen"}


def _sim(decisions: list[dict]) -> tuple[UserSimulator, _StubLLM]:
    llm = _StubLLM(decisions)
    sim = UserSimulator(_scenario(), "vi_north_normal", model="stub", guidelines="G", llm=llm)
    return sim, llm


def test_opening_returns_initial_intent():
    sim, _ = _sim([])
    assert sim.opening() == "Bật điều hòa ghế lái"


def test_observe_flags_checkpoints_and_accumulates_transcript():
    sim, _ = _sim([])
    assert sim.observe({"type": "assistant_text_delta", "text": "Đang bật điều hòa "}) is False
    assert sim.observe({"type": "assistant_text_delta", "text": "ghế lái"}) is False
    assert sim.observe({"type": "assistant_speech_start", "t_ms": 100}) is True
    assert sim.observe({"type": "tool_call", "tool": "climate_control", "args": {"position": "driver"}}) is True
    assert sim.agent_transcript() == "Đang bật điều hòa ghế lái"


def test_observe_records_last_tool_call():
    sim, _ = _sim([])
    sim.observe({"type": "tool_call", "tool": "climate_control", "args": {"position": "driver"}})
    assert sim._last_tool_call == {"tool": "climate_control", "args": {"position": "driver"}}


def test_decide_calls_llm_only_when_invoked():
    sim, llm = _sim([{"action": "bargein", "utterance": "Ghế phụ"}])
    # Observing several non-checkpoint events does not call the LLM.
    sim.observe({"type": "assistant_text_delta", "text": "a"})
    sim.observe({"type": "assistant_text_delta", "text": "b"})
    assert llm.calls == []
    action = asyncio.run(sim.decide())
    assert action == Action(kind="bargein", utterance="Ghế phụ")
    assert len(llm.calls) == 1


def test_decide_coerces_unknown_action_to_listen():
    sim, _ = _sim([{"action": "explode", "utterance": "x"}])
    action = asyncio.run(sim.decide())
    assert action.kind == "listen"


def test_decide_blank_utterance_becomes_none():
    sim, _ = _sim([{"action": "listen", "utterance": "   "}])
    action = asyncio.run(sim.decide())
    assert action.utterance is None


def test_build_scenario_from_overlay():
    overlay = {
        "speech_overlay_id": "fdrc_007",
        "domain": "navigation",
        "initial_spoken_utterance": "Dẫn đường tới Vincom",
        "repair_utterance": "Vincom Bà Triệu cơ",
        "expected_final_state": {"committed_intent": "fdrc_007"},
    }
    task = {"domain": "navigation", "user_goal": "x"}
    scenario = build_scenario(overlay, task)
    assert scenario.opening_intent == "Dẫn đường tới Vincom"
    assert scenario.true_goal == "Vincom Bà Triệu cơ"
    assert scenario.overlay_id == "fdrc_007"
    assert scenario.domain == "navigation"


def test_trace_round_trip(tmp_path):
    scenario = _scenario()
    trace = SimTrace(
        opening="Bật điều hòa ghế lái",
        barge_in_t_ms=2300,
        repair_text="Ghế phụ",
        stop_reason="###STOP###",
        actions=[{"kind": "bargein", "utterance": "Ghế phụ"}],
    )
    save_trace(tmp_path, scenario, "vi_north_normal", "stub", trace)
    loaded = load_trace(tmp_path, scenario, "vi_north_normal", "stub")
    assert loaded == trace
    assert load_trace(tmp_path, scenario, "vi_north_normal", "other_model") is None


def test_scenario_hash_is_stable_and_sensitive():
    a = _scenario()
    b = _scenario()
    assert a.hash() == b.hash()
    c = Scenario(
        overlay_id="fdrc_001",
        domain="automotive",
        opening_intent="khác",
        true_goal="x",
    )
    assert c.hash() != a.hash()
