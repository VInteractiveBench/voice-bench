from __future__ import annotations

import asyncio
import time
from typing import Literal

from src.adapters import (
    GeminiLiveViviAdapter,
    OpenAIRealtimeViviAdapter,
    OpenAITextViviAdapter,
    ViviAgentAdapter,
)
from src.adapters.prompts import build_system_prompt
from src.audio import audio_io
from src.audio.audio_cache import AudioCache
from src.tools import MockToolServer, get_openai_tool_schemas
from src.schema import MODE_TO_AUDIO_CONDITION
from src.tools.vivi_tool_registry import get_domain_tools
from src.tick_scheduler import schedule_timeline
from src.orchestrator.user_simulator import (
    DEFAULT_SIM_TRACE_DIR,
    DEFAULT_SIMULATOR_MODEL,
    SimTrace,
    UserSimulator,
    build_scenario,
    load_trace,
    save_trace,
)


AgentName = Literal["openai_text", "openai_realtime", "gemini_live"]

AGENT_TO_PROVIDER: dict[str, str] = {
    "openai_text": "openai",
    "openai_realtime": "openai",
    "gemini_live": "google",
}


def provider_for_agent(agent: str | None) -> str | None:
    return AGENT_TO_PROVIDER.get(agent) if agent else None


_AUDIO_CACHE: AudioCache | None = None


def _get_audio_cache() -> AudioCache:
    global _AUDIO_CACHE
    if _AUDIO_CACHE is None:
        _AUDIO_CACHE = AudioCache()
    return _AUDIO_CACHE


def _persona_parts(persona: str) -> tuple[str, str]:
    accent, speed = persona.removeprefix("vi_").rsplit("_", 1)
    return accent, speed


def _episode_id(
    overlay: dict,
    mode: str,
    persona: str,
    agent: str,
    model: str,
    *,
    audio_condition_id: str | None = None,
) -> str:
    condition = f":{audio_condition_id}" if audio_condition_id else ""
    return f"{overlay['speech_overlay_id']}:{mode}:{persona}{condition}:{agent}:{model}"


def tool_schemas_for_agent(agent: str, domain: str | None) -> list[dict]:
    # Only openai_text runs OpenAI strict mode; realtime and gemini do not enforce
    # it, so they get non-strict schemas (optionals stay optional, not forced).
    return get_openai_tool_schemas(domain, strict=(agent == "openai_text"))


def build_adapter(agent: AgentName, model: str) -> ViviAgentAdapter:
    if agent == "openai_text":
        return OpenAITextViviAdapter(model=model)
    if agent == "openai_realtime":
        return OpenAIRealtimeViviAdapter(model=model)
    if agent == "gemini_live":
        return GeminiLiveViviAdapter(model=model)
    raise ValueError(f"Unsupported agent: {agent}")


async def run_agent_episode(
    *,
    agent: AgentName,
    model: str,
    task: dict,
    overlay: dict,
    mode: str,
    persona: str,
    tick_ms: int = 200,
    fdrc_yield_mode: str = "native_yield",
    audio_condition_id: str | None = None,
    simulator_mode: str = "off",
    simulator_model: str = DEFAULT_SIMULATOR_MODEL,
    sim_trace_dir: str = str(DEFAULT_SIM_TRACE_DIR),
) -> dict:
    adapter = build_adapter(agent, model)
    tool_schemas = tool_schemas_for_agent(agent, task["domain"])
    tool_names = get_domain_tools(task["domain"])
    system_prompt = build_system_prompt(
        task=task,
        overlay=overlay,
        mode=mode,
        tool_names=tool_names,
    )
    server = MockToolServer(task["domain"], task, overlay)
    normalized_events: list[dict] = []
    assistant_transcript: list[str] = []
    user_transcript: list[str] = []
    failures: list[str] = []

    await adapter.start_session(system_prompt=system_prompt, tools=tool_schemas)
    try:
        if agent in {"openai_realtime", "gemini_live"}:
            await _run_audio_episode(
                adapter, task, overlay, mode, persona, server,
                normalized_events, assistant_transcript, user_transcript, failures,
                fdrc_yield_mode=fdrc_yield_mode,
                audio_condition_id=audio_condition_id,
                simulator_mode=simulator_mode,
                simulator_model=simulator_model,
                sim_trace_dir=sim_trace_dir,
            )
        elif overlay["benchmark_track"] == "full_duplex_repair_to_commit":
            await _send_timeline_text(adapter, overlay, normalized_events, user_transcript, tick_ms)
            await _drain_adapter_events(adapter, server, normalized_events, assistant_transcript, failures)
        else:
            text = overlay.get("user_utterance") or overlay.get("spoken_utterance") or task.get("user_goal", "")
            user_transcript.append(text)
            normalized_events.append({"type": "user_audio_chunk_sent", "t_ms": 0, "text": text})
            await adapter.send_text(text)
            await _drain_adapter_events(adapter, server, normalized_events, assistant_transcript, failures)
    finally:
        await adapter.close()

    accent, speed = _persona_parts(persona)
    condition = audio_condition_id or _audio_condition_for_mode(mode)
    normalized_events = _normalize_repair_transcript_events(normalized_events)
    return {
        "episode_id": _episode_id(
            overlay,
            mode,
            persona,
            agent,
            model,
            audio_condition_id=audio_condition_id,
        ),
        "agent": "openai_as_vivi",
        "provider": provider_for_agent(agent),
        "model": model,
        "adapter": agent,
        "benchmark_track": overlay["benchmark_track"],
        "domain": task["domain"],
        "base_task_id": task["id"],
        "speech_overlay_id": overlay["speech_overlay_id"],
        "mode": mode,
        "accent_region": accent,
        "speech_speed": speed,
        "audio_condition_id": condition,
        "fdrc_yield_mode": fdrc_yield_mode if overlay["benchmark_track"] == "full_duplex_repair_to_commit" else None,
        "initial_state": server.initial_state,
        "final_state": server.final_state(),
        "user_transcript": user_transcript,
        "assistant_transcript": assistant_transcript,
        "captured_slots": _infer_captured_slots(overlay, server.tool_call_log),
        "normalized_events": normalized_events,
        "voice_events": _voice_events_from_normalized(
            normalized_events, overlay, server.final_state()
        ),
        "tool_calls": server.tool_call_log,
        "tool_results": server.tool_results,
        "validation_errors": [err for result in server.tool_results for err in result.get("errors", [])],
        "policy_violations": [],
        "latency": {
            "response_latency_ms": _first_event_time(normalized_events, "assistant_text_delta"),
            "yield_latency_ms": _yield_latency(normalized_events),
        },
        "scores": {"task_pass": 0, "policy_pass": 0, "voice_pass": 0, "final_pass": 0},
        "failure_types": failures,
    }


def failed_episode_stub(
    *,
    agent: str,
    model: str,
    task: dict,
    overlay: dict,
    mode: str,
    persona: str,
    audio_condition_id: str | None,
    error: BaseException,
    fdrc_yield_mode: str = "native_yield",
) -> dict:
    """Minimal episode record for an episode that crashed at runtime (e.g. a realtime
    websocket drop). Keeps the batch alive and records the failure honestly instead of
    aborting the whole run and discarding every completed episode."""
    accent, speed = _persona_parts(persona)
    is_fdrc = overlay["benchmark_track"] == "full_duplex_repair_to_commit"
    return {
        "episode_id": _episode_id(overlay, mode, persona, agent, model, audio_condition_id=audio_condition_id),
        "agent": "openai_as_vivi",
        "provider": provider_for_agent(agent),
        "model": model,
        "adapter": agent,
        "benchmark_track": overlay["benchmark_track"],
        "domain": task["domain"],
        "base_task_id": task["id"],
        "speech_overlay_id": overlay["speech_overlay_id"],
        "mode": mode,
        "accent_region": accent,
        "speech_speed": speed,
        "audio_condition_id": audio_condition_id or _audio_condition_for_mode(mode),
        "fdrc_yield_mode": fdrc_yield_mode if is_fdrc else None,
        "initial_state": dict(task.get("initial_state", {})),
        "final_state": {},
        "user_transcript": [],
        "assistant_transcript": [],
        "captured_slots": {},
        "normalized_events": [],
        "voice_events": [],
        "tool_calls": [],
        "tool_results": [],
        "validation_errors": [],
        "policy_violations": [],
        "latency": {"response_latency_ms": None, "yield_latency_ms": None},
        "scores": {"task_pass": 0, "policy_pass": 0, "voice_pass": 0, "final_pass": 0},
        "failure_types": ["EPISODE_RUNTIME_ERROR"],
        "runtime_error": f"{type(error).__name__}: {error}",
    }


async def _send_timeline_text(
    adapter: ViviAgentAdapter,
    overlay: dict,
    normalized_events: list[dict],
    user_transcript: list[str],
    tick_ms: int,
) -> None:
    for event in schedule_timeline(overlay.get("voice_timeline", []), tick_ms):
        if event.get("event") == "user_speech_start":
            text = overlay.get("initial_spoken_utterance", event.get("text", ""))
            user_transcript.append(text)
            normalized_events.append({"type": "user_audio_chunk_sent", "t_ms": event["t_ms"], "text": text})
            await adapter.send_text(text)
        elif event.get("event") == "user_interrupt_start":
            text = overlay.get("repair_utterance", event.get("text", ""))
            user_transcript.append(text)
            normalized_events.append({"type": "user_audio_chunk_sent", "t_ms": event["t_ms"], "text": text, "overlap": True})
            await adapter.send_text(text)
        else:
            normalized_events.append({"type": event["event"], "t_ms": event["t_ms"], **{k: v for k, v in event.items() if k not in {"event", "t_ms"}}})


async def _stream_audio(
    adapter: ViviAgentAdapter,
    samples,
    normalized_events: list[dict],
    *,
    episode_started: float,
    overlap: bool,
) -> None:
    """Stream float samples as 100 ms PCM16 chunks on wall-clock time."""
    pcm = audio_io.float_to_pcm16(samples)
    frame_bytes = int(0.1 * audio_io.TARGET_SR) * 2  # 100 ms of mono PCM16
    marker_logged = False
    for offset in range(0, len(pcm), frame_bytes):
        t_ms = int((time.perf_counter() - episode_started) * 1000)
        if not marker_logged:
            normalized_events.append(
                {"type": "user_audio_chunk_sent", "t_ms": t_ms, "overlap": overlap}
            )
            marker_logged = True
        await adapter.send_audio_chunk(pcm[offset:offset + frame_bytes], t_ms)
        await asyncio.sleep(0.1)


def _timeline_interrupt_ms(overlay: dict, default: int = 2000) -> int:
    for event in overlay.get("voice_timeline", []):
        if event.get("event") == "user_interrupt_start" and isinstance(event.get("t_ms"), int):
            return event["t_ms"]
    return default


BARGE_IN_OFFSET_MS = 500
BARGE_IN_SPEECH_WAIT_CAP_MS = 15000


async def _await_barge_in(
    normalized_events: list[dict],
    *,
    episode_started: float,
    scripted_interrupt_ms: int,
    offset_ms: int = BARGE_IN_OFFSET_MS,
    cap_ms: int = BARGE_IN_SPEECH_WAIT_CAP_MS,
) -> None:
    """Wait until the repair should barge in. Instead of a fixed wall-clock interrupt
    (which lands before slow providers even start speaking), wait for the assistant to
    actually start speaking, then barge in `offset_ms` into its response — but never
    earlier than the scripted interrupt point (so fast providers are unaffected). If the
    assistant never starts speaking within `cap_ms`, fall back to the scripted time."""
    deadline = episode_started + cap_ms / 1000
    while time.perf_counter() < deadline:
        if any(event.get("type") == "assistant_speech_start" for event in normalized_events):
            break
        await asyncio.sleep(0.05)
    spoke = any(event.get("type") == "assistant_speech_start" for event in normalized_events)
    scripted_target = episode_started + scripted_interrupt_ms / 1000
    if spoke:
        target = max(scripted_target, time.perf_counter() + offset_ms / 1000)
    else:
        target = scripted_target
    await asyncio.sleep(max(0.0, target - time.perf_counter()))


async def _run_audio_episode(
    adapter: ViviAgentAdapter,
    task: dict,
    overlay: dict,
    mode: str,
    persona: str,
    server: MockToolServer,
    normalized_events: list[dict],
    assistant_transcript: list[str],
    user_transcript: list[str],
    failures: list[str],
    fdrc_yield_mode: str = "native_yield",
    audio_condition_id: str | None = None,
    simulator_mode: str = "off",
    simulator_model: str = DEFAULT_SIMULATOR_MODEL,
    sim_trace_dir: str = str(DEFAULT_SIM_TRACE_DIR),
) -> None:
    """Drive a voice/FDRC episode with real synthesized audio over the realtime session."""
    cache = _get_audio_cache()
    accent, speed = _persona_parts(persona)
    condition = audio_condition_id or MODE_TO_AUDIO_CONDITION[mode]

    if overlay["benchmark_track"] == "full_duplex_repair_to_commit":
        if simulator_mode == "live":
            await _run_live_simulated_repair(
                adapter, task, overlay, persona, server, condition,
                normalized_events, assistant_transcript, user_transcript, failures,
                fdrc_yield_mode=fdrc_yield_mode,
                simulator_model=simulator_model,
                sim_trace_dir=sim_trace_dir,
            )
            return
        if simulator_mode == "replay":
            scenario = build_scenario(overlay, task)
            trace = load_trace(sim_trace_dir, scenario, persona, simulator_model)
            if trace is not None:
                await _run_scripted_repair(
                    adapter, server, condition, accent, speed,
                    normalized_events, assistant_transcript, user_transcript, failures,
                    initial_text=trace.opening,
                    repair_text=trace.repair_text or scenario.true_goal,
                    interrupt_ms=trace.barge_in_t_ms or _timeline_interrupt_ms(overlay),
                    fdrc_yield_mode=fdrc_yield_mode,
                )
                return
            # No recorded trace yet: fall through to a live run that records one.
            await _run_live_simulated_repair(
                adapter, task, overlay, persona, server, condition,
                normalized_events, assistant_transcript, user_transcript, failures,
                fdrc_yield_mode=fdrc_yield_mode,
                simulator_model=simulator_model,
                sim_trace_dir=sim_trace_dir,
            )
            return
        await _run_scripted_repair(
            adapter, server, condition, accent, speed,
            normalized_events, assistant_transcript, user_transcript, failures,
            initial_text=overlay.get("initial_spoken_utterance", ""),
            repair_text=overlay.get("repair_utterance", ""),
            interrupt_ms=_timeline_interrupt_ms(overlay),
            fdrc_yield_mode=fdrc_yield_mode,
        )
        return

    text = overlay.get("user_utterance") or overlay.get("spoken_utterance") or task.get("user_goal", "")
    samples = cache.get_or_build(text, accent, speed, condition)
    user_transcript.append(text)
    await _stream_audio(
        adapter,
        samples,
        normalized_events,
        episode_started=time.perf_counter(),
        overlap=False,
    )
    await adapter.commit_audio_turn()
    await _drain_adapter_events(adapter, server, normalized_events, assistant_transcript, failures)


async def _run_scripted_repair(
    adapter: ViviAgentAdapter,
    server: MockToolServer,
    condition: str,
    accent: str,
    speed: str,
    normalized_events: list[dict],
    assistant_transcript: list[str],
    user_transcript: list[str],
    failures: list[str],
    *,
    initial_text: str,
    repair_text: str,
    interrupt_ms: int,
    fdrc_yield_mode: str,
) -> None:
    """Deterministic FDRC repair: stream the (fixed) initial then repair audio, barging in
    after the assistant starts speaking. Used by ``simulator_mode`` ``off`` (from overlay)
    and ``replay`` (from a recorded SimTrace)."""
    cache = _get_audio_cache()
    initial = cache.get_or_build(initial_text, accent, speed, condition)
    repair = cache.get_or_build(repair_text, accent, speed, condition)
    user_transcript.extend([initial_text, repair_text])
    # Drain concurrently so the repair audio can overlap the assistant's response.
    episode_started = time.perf_counter()
    # Align the adapter's event clock with the episode clock so observed
    # assistant_speech_start and the orchestrator-stamped user_interrupt_start are
    # comparable; otherwise the ~1-2s session-open gap makes a real barge-in look
    # like the assistant spoke after the interrupt.
    adapter._started = episode_started
    drain = asyncio.create_task(
        _drain_adapter_events(adapter, server, normalized_events, assistant_transcript, failures)
    )
    await _stream_audio(
        adapter, initial, normalized_events, episode_started=episode_started, overlap=False
    )
    await adapter.commit_audio_turn()
    await _await_barge_in(
        normalized_events,
        episode_started=episode_started,
        scripted_interrupt_ms=interrupt_ms,
    )
    if fdrc_yield_mode == "client_cancel_yield":
        normalized_events.append(
            {"type": "client_cancel_response", "t_ms": int((time.perf_counter() - episode_started) * 1000)}
        )
        await adapter.cancel_response()
    await _stream_audio(
        adapter, repair, normalized_events, episode_started=episode_started, overlap=True
    )
    await adapter.commit_audio_turn()
    await drain


SIM_SETTLE_S = 1.2
SIM_MAX_DECISIONS = 6
SIM_OVERALL_CAP_MS = BARGE_IN_SPEECH_WAIT_CAP_MS


async def _run_live_simulated_repair(
    adapter: ViviAgentAdapter,
    task: dict,
    overlay: dict,
    persona: str,
    server: MockToolServer,
    condition: str,
    normalized_events: list[dict],
    assistant_transcript: list[str],
    user_transcript: list[str],
    failures: list[str],
    *,
    fdrc_yield_mode: str,
    simulator_model: str,
    sim_trace_dir: str,
) -> None:
    """Live FDRC repair driven by a real LLM user simulator (checkpoint-gated).

    The simulator opens with its initial intent, listens to the agent via a checkpoint
    queue fed by the drain loop, and decides at each checkpoint whether to keep listening,
    barge in (synthesizing a dynamic repair), confirm, or stop. The realized opening text,
    barge-in time and repair text are recorded as a SimTrace for deterministic replay."""
    cache = _get_audio_cache()
    accent, speed = _persona_parts(persona)
    scenario = build_scenario(overlay, task)
    simulator = UserSimulator(scenario, persona, model=simulator_model)

    checkpoints: asyncio.Queue[int | None] = asyncio.Queue()

    def _on_event(event: dict) -> None:
        if simulator.observe(event):
            checkpoints.put_nowait(event.get("t_ms"))

    opening_text = simulator.opening()
    opening = cache.get_or_build(opening_text, accent, speed, condition)
    user_transcript.append(opening_text)

    episode_started = time.perf_counter()
    adapter._started = episode_started
    drain = asyncio.create_task(
        _drain_adapter_events(
            adapter, server, normalized_events, assistant_transcript, failures, on_event=_on_event
        )
    )
    await _stream_audio(
        adapter, opening, normalized_events, episode_started=episode_started, overlap=False
    )
    await adapter.commit_audio_turn()

    trace = SimTrace(opening=opening_text)
    deadline = episode_started + SIM_OVERALL_CAP_MS / 1000
    decisions = 0
    while not trace.barge_in_t_ms and decisions < SIM_MAX_DECISIONS:
        if time.perf_counter() >= deadline:
            break
        try:
            await asyncio.wait_for(checkpoints.get(), timeout=SIM_SETTLE_S)
        except asyncio.TimeoutError:
            # Agent went quiet without a new checkpoint: treat the settle as a checkpoint
            # only once the agent has actually started speaking, otherwise keep waiting.
            if not any(e.get("type") == "assistant_speech_start" for e in normalized_events):
                continue
        decisions += 1
        action = await simulator.decide()
        if action.kind == "bargein":
            repair_text = action.utterance or scenario.true_goal
            repair = cache.get_or_build(repair_text, accent, speed, condition)
            if fdrc_yield_mode == "client_cancel_yield":
                normalized_events.append(
                    {"type": "client_cancel_response", "t_ms": int((time.perf_counter() - episode_started) * 1000)}
                )
                await adapter.cancel_response()
            await _stream_audio(
                adapter, repair, normalized_events, episode_started=episode_started, overlap=True
            )
            await adapter.commit_audio_turn()
            user_transcript.append(repair_text)
            trace.barge_in_t_ms = _first_overlap_marker_ms(normalized_events)
            trace.repair_text = repair_text
        elif action.kind in {"confirm", "stop"}:
            trace.stop_reason = action.utterance or action.kind
            break
    trace.actions = list(simulator.actions)
    await drain
    save_trace(sim_trace_dir, scenario, persona, simulator_model, trace)


def _first_overlap_marker_ms(events: list[dict]) -> int | None:
    return next(
        (
            event.get("t_ms")
            for event in events
            if event.get("type") == "user_audio_chunk_sent" and event.get("overlap")
        ),
        None,
    )


async def _drain_adapter_events(
    adapter: ViviAgentAdapter,
    server: MockToolServer,
    normalized_events: list[dict],
    assistant_transcript: list[str],
    failures: list[str],
    on_event=None,
) -> None:
    async for event in adapter.receive_events():
        normalized_events.append(dict(event))
        if on_event is not None:
            on_event(dict(event))
        event_type = event.get("type")
        if event_type in {"assistant_text_delta", "assistant_transcript_delta"}:
            text = event.get("text")
            if text:
                assistant_transcript.append(text)
        elif event_type == "tool_call":
            try:
                result = server.execute(
                    event.get("tool", ""),
                    event.get("args", {}),
                    t_ms=event.get("t_ms"),
                )
            except Exception as exc:
                failures.append("OPENAI_TOOL_CALL_PARSE_ERROR")
                result = None
                normalized_events.append(
                    {"type": "tool_result", "t_ms": event.get("t_ms", 0), "error": str(exc)}
                )
            if result is not None:
                normalized_events.append(
                    {
                        "type": "tool_result",
                        "t_ms": event.get("t_ms", 0),
                        "tool": event.get("tool"),
                        "result": result.content,
                    }
                )
                await adapter.send_tool_result(event.get("call_id", ""), result.content)
        elif event_type == "session_error":
            failures.append("OPENAI_SESSION_ERROR")


def _audio_condition_for_mode(mode: str) -> str:
    return MODE_TO_AUDIO_CONDITION[mode]


def _infer_captured_slots(overlay: dict, tool_calls: list[dict]) -> dict:
    expected = overlay.get("expected_critical_slots", {})
    if not tool_calls:
        return {}
    text = " ".join(str(call.get("args", {})) for call in tool_calls)
    return {key: value for key, value in expected.items() if str(value) in text}


def _voice_events_from_normalized(
    events: list[dict], overlay: dict, final_state: dict | None = None
) -> list[dict]:
    voice_events = [
        {**event, "source": "expected"} for event in overlay.get("voice_timeline", [])
    ]
    for event in events:
        event_type = event.get("type")
        t_ms = event.get("t_ms")
        if not isinstance(t_ms, int):
            continue
        if event_type == "assistant_speech_start":
            voice_events.append({"event": "assistant_speech_start", "t_ms": t_ms, "source": "observed"})
        elif event_type == "assistant_speech_stop":
            voice_events.append({"event": "assistant_speech_stop", "t_ms": t_ms, "source": "observed"})
        elif event_type == "user_audio_chunk_sent" and event.get("overlap"):
            voice_events.append({"event": "user_interrupt_start", "t_ms": t_ms, "source": "observed"})
            voice_events.append({"event": "repair_audio_start", "t_ms": t_ms, "source": "observed"})
        elif event_type == "tool_call":
            voice_events.append(
                {
                    "event": "tool_call",
                    "t_ms": t_ms,
                    "tool": event.get("tool"),
                    "args": event.get("args"),
                    "source": "observed",
                }
            )
        elif event_type == "tool_result":
            voice_events.append(
                {
                    "event": "tool_result",
                    "t_ms": t_ms,
                    "tool": event.get("tool"),
                    "source": "observed",
                }
            )
        elif event_type == "repair_transcript_done":
            voice_events.append(
                {"event": "repair_transcript_done", "t_ms": t_ms, "source": "observed"}
            )
    interrupt = next(
        (
            e["t_ms"]
            for e in voice_events
            if e.get("event") == "user_interrupt_start" and e.get("source") == "observed"
        ),
        None,
    )
    repair_transcript = _first_event_time_after(events, "repair_transcript_done", interrupt)
    if repair_transcript is None:
        repair_transcript = _first_event_time_after(events, "user_transcript_done", interrupt)
    if repair_transcript is not None and not any(
        event.get("event") == "repair_transcript_done"
        and event.get("source") == "observed"
        for event in voice_events
    ):
        voice_events.append(
            {"event": "repair_transcript_done", "t_ms": repair_transcript, "source": "observed"}
        )
    speech_stop = _first_event_time_after(events, "assistant_speech_stop", interrupt)
    if interrupt is not None and speech_stop is not None:
        voice_events.append({"event": "assistant_yielded", "t_ms": speech_stop, "source": "observed"})
    last_t_ms = max(
        [event.get("t_ms", 0) for event in voice_events if isinstance(event.get("t_ms"), int)]
        or [0]
    )
    if final_state is not None:
        voice_events.append(
            {
                "event": "final_state",
                "t_ms": last_t_ms + 1,
                "state": final_state,
                "source": "observed",
            }
        )
    return sorted(voice_events, key=lambda event: event.get("t_ms", 0))


def _first_event_time(events: list[dict], event_type: str) -> int | None:
    return next((event.get("t_ms") for event in events if event.get("type") == event_type), None)


def _first_event_time_after(
    events: list[dict], event_type: str, after_ms: int | None
) -> int | None:
    return next(
        (
            event.get("t_ms")
            for event in events
            if event.get("type") == event_type
            and (after_ms is None or event.get("t_ms", -1) >= after_ms)
        ),
        None,
    )


def _normalize_repair_transcript_events(events: list[dict]) -> list[dict]:
    interrupt = next(
        (
            event.get("t_ms")
            for event in events
            if event.get("type") == "user_audio_chunk_sent" and event.get("overlap")
        ),
        None,
    )
    if interrupt is None:
        return events
    normalized = list(events)
    has_repair_done = any(
        event.get("type") == "repair_transcript_done"
        and isinstance(event.get("t_ms"), int)
        and event.get("t_ms") >= interrupt
        for event in normalized
    )
    if has_repair_done:
        return normalized
    for event in events:
        if (
            event.get("type") == "user_transcript_done"
            and isinstance(event.get("t_ms"), int)
            and event.get("t_ms") >= interrupt
        ):
            normalized.append(
                {
                    **event,
                    "type": "repair_transcript_done",
                    "source_type": "user_transcript_done",
                }
            )
            break
    return sorted(normalized, key=lambda event: event.get("t_ms", 0))


def _yield_latency(events: list[dict]) -> int | None:
    interrupt = next(
        (event.get("t_ms") for event in events if event.get("type") == "user_audio_chunk_sent" and event.get("overlap")),
        None,
    )
    stop = _first_event_time_after(events, "assistant_speech_stop", interrupt)
    return stop - interrupt if interrupt is not None and stop is not None else None
