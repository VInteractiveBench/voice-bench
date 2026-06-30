"""Real LLM-driven user simulator for the FDRC track.

The simulator plays the in-car DRIVER. It opens with an initial intent (which may be
vague or mis-stated), listens to the agent's live response, and decides at *semantic
checkpoints* (a tool_call, an assistant_speech_start, or a settled transcript) whether to
keep listening, barge in to correct the agent, confirm, or stop.

LLM calls are gated to checkpoints (Approach A: checkpoint-gated monitor) so latency and
cost stay bounded — never one call per streamed delta.

The LLM driver is injectable (``llm=``) so the class is unit-testable without network
access. The default driver uses the OpenAI text API (fixed, separate from the
agent-under-test, for fairness).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Awaitable, Callable

GUIDELINES_DIR = Path("data") / "user_simulator"
DEFAULT_SIM_TRACE_DIR = Path("data") / "simulator_traces"
DEFAULT_SIMULATOR_MODEL = "gpt-4o-mini"

CHECKPOINT_EVENT_TYPES = {"tool_call", "assistant_speech_start"}
STOP_TOKENS = {"###STOP###", "###TRANSFER###", "###OUT-OF-SCOPE###"}

# An injected LLM driver maps (system_prompt, user_prompt, model) -> decision dict.
LLMDriver = Callable[[str, str, str], Awaitable[dict]]


@dataclass
class Action:
    """One decision from the simulator at a checkpoint."""

    kind: str  # "listen" | "bargein" | "confirm" | "stop"
    utterance: str | None = None


@dataclass
class Scenario:
    """The driver's situation, derived from an FDRC overlay + base task."""

    overlay_id: str
    domain: str
    opening_intent: str  # initial spoken utterance (may be vague/wrong)
    true_goal: str  # natural-language statement of the corrected/true intent
    expected_final_state: dict = field(default_factory=dict)

    def hash(self) -> str:
        payload = json.dumps(asdict(self), ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


@dataclass
class SimTrace:
    """Recording of a live run, replayed deterministically afterwards."""

    opening: str
    barge_in_t_ms: int | None = None
    repair_text: str | None = None
    stop_reason: str | None = None
    actions: list[dict] = field(default_factory=list)


def build_scenario(overlay: dict, task: dict) -> Scenario:
    """Construct a Scenario from an FDRC overlay. The opening is the initial (possibly
    mis-stated) utterance; the true goal is the user's correction — the same content the
    scripted ``repair_utterance`` encodes — so evaluator expectations stay aligned."""
    opening = (
        overlay.get("initial_spoken_utterance")
        or overlay.get("spoken_utterance")
        or task.get("user_goal", "")
    )
    true_goal = (
        overlay.get("repair_utterance")
        or overlay.get("user_goal")
        or task.get("user_goal", "")
    )
    return Scenario(
        overlay_id=overlay.get("speech_overlay_id", ""),
        domain=task.get("domain", overlay.get("domain", "")),
        opening_intent=opening,
        true_goal=true_goal,
        expected_final_state=overlay.get(
            "expected_final_state", task.get("expected_final_state", {})
        ),
    )


def load_guidelines(directory: Path | str = GUIDELINES_DIR) -> str:
    """Concatenate the Vietnamese in-car simulation guideline files."""
    directory = Path(directory)
    parts = []
    for name in (
        "simulation_guidelines.md",
        "simulation_guidelines_voice.md",
        "simulation_guidelines_tools.md",
    ):
        path = directory / name
        if path.exists():
            parts.append(path.read_text(encoding="utf-8"))
    return "\n\n".join(parts)


def trace_key(scenario: Scenario, persona: str, model: str) -> str:
    return f"{scenario.overlay_id}:{persona}:{scenario.hash()}:{model}"


def trace_path(trace_dir: Path | str, scenario: Scenario, persona: str, model: str) -> Path:
    safe = trace_key(scenario, persona, model).replace("/", "_").replace(":", "__")
    return Path(trace_dir) / f"{safe}.json"


def save_trace(
    trace_dir: Path | str, scenario: Scenario, persona: str, model: str, trace: SimTrace
) -> Path:
    path = trace_path(trace_dir, scenario, persona, model)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(asdict(trace), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return path


def load_trace(
    trace_dir: Path | str, scenario: Scenario, persona: str, model: str
) -> SimTrace | None:
    path = trace_path(trace_dir, scenario, persona, model)
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return SimTrace(**data)


class UserSimulator:
    """Checkpoint-gated user simulator. See module docstring."""

    def __init__(
        self,
        scenario: Scenario,
        persona: str,
        *,
        model: str = DEFAULT_SIMULATOR_MODEL,
        guidelines: str | None = None,
        llm: LLMDriver | None = None,
    ) -> None:
        self.scenario = scenario
        self.persona = persona
        self.model = model
        self.guidelines = guidelines if guidelines is not None else load_guidelines()
        self._llm: LLMDriver = llm or _openai_llm_driver
        self._agent_transcript: list[str] = []
        self._last_tool_call: dict | None = None
        self.actions: list[dict] = []

    def opening(self) -> str:
        return self.scenario.opening_intent

    def observe(self, event: dict) -> bool:
        """Accumulate agent output. Return True if this event is a semantic checkpoint
        at which the orchestrator should call :meth:`decide`."""
        event_type = event.get("type")
        if event_type in {"assistant_text_delta", "assistant_transcript_delta"}:
            text = event.get("text")
            if text:
                self._agent_transcript.append(text)
        if event_type == "tool_call":
            self._last_tool_call = {
                "tool": event.get("tool"),
                "args": event.get("args"),
            }
            return True
        return event_type in CHECKPOINT_EVENT_TYPES

    def agent_transcript(self) -> str:
        return "".join(self._agent_transcript).strip()

    async def decide(self) -> Action:
        system_prompt, user_prompt = self._build_prompts()
        raw = await self._llm(system_prompt, user_prompt, self.model)
        action = _coerce_action(raw)
        self.actions.append(asdict(action))
        return action

    def _build_prompts(self) -> tuple[str, str]:
        system = (
            f"{self.guidelines}\n\n"
            f"## Persona\nBạn nói giọng/tốc độ theo persona: {self.persona}.\n\n"
            "## Định dạng đầu ra (BẮT BUỘC)\n"
            "Chỉ trả về JSON đúng dạng: "
            '{"action": "listen|bargein|confirm|stop", "utterance": "<lời nói tiếng Việt hoặc rỗng>"}.\n'
            "- listen: chưa nói gì, tiếp tục nghe (utterance rỗng).\n"
            "- bargein: chen ngang để SỬA vì Vivi đang đi sai mục tiêu thật (utterance = lời sửa ngắn).\n"
            "- confirm: Vivi làm đúng, xác nhận ngắn (utterance = lời xác nhận).\n"
            "- stop: kết thúc; utterance là một trong "
            f"{sorted(STOP_TOKENS)}.\n"
        )
        tool = self._last_tool_call
        user = (
            f"BỐI CẢNH (chỉ bạn biết):\n"
            f"- Ý định ban đầu bạn đã nói: {self.scenario.opening_intent!r}\n"
            f"- MỤC TIÊU THẬT cần đạt: {self.scenario.true_goal!r}\n\n"
            f"Vivi đang phản hồi (nội dung tới hiện tại): {self.agent_transcript()!r}\n"
            f"Hành động/công cụ Vivi vừa gọi: {json.dumps(tool, ensure_ascii=False) if tool else 'chưa có'}\n\n"
            "Bạn (tài xế) làm gì NGAY BÂY GIỜ? Trả về đúng JSON."
        )
        return system, user


def _coerce_action(raw: dict) -> Action:
    kind = str(raw.get("action", "listen")).strip().lower()
    if kind not in {"listen", "bargein", "confirm", "stop"}:
        kind = "listen"
    utterance = raw.get("utterance")
    if utterance is not None:
        utterance = str(utterance).strip() or None
    return Action(kind=kind, utterance=utterance)


async def _openai_llm_driver(system_prompt: str, user_prompt: str, model: str) -> dict:
    """Default driver: OpenAI text API in JSON mode, run off the event loop thread."""
    return await asyncio.to_thread(_openai_llm_sync, system_prompt, user_prompt, model)


def _openai_llm_sync(system_prompt: str, user_prompt: str, model: str) -> dict:
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is required for the user simulator")
    try:
        from openai import OpenAI
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise RuntimeError("The openai package is required for the user simulator") from exc
    client = OpenAI()
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        response_format={"type": "json_object"},
        temperature=0.7,
    )
    content = response.choices[0].message.content or "{}"
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return {"action": "listen"}
