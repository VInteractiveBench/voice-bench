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
) -> dict:
    adapter = build_adapter(agent, model)
    tool_schemas = get_openai_tool_schemas(task["domain"])
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
            )
        elif overlay["benchmark_track"] == "full_duplex_repair_to_commit":
            await _send_timeline_text(adapter, overlay, normalized_events, user_transcript, tick_ms)
            await _drain_adapter_events(adapter, server, normalized_events, assistant_transcript, failures)
        else:
            text = overlay.get("spoken_utterance") or task.get("user_goal", "")
            user_transcript.append(text)
            normalized_events.append({"type": "user_audio_chunk_sent", "t_ms": 0, "text": text})
            await adapter.send_text(text)
            await _drain_adapter_events(adapter, server, normalized_events, assistant_transcript, failures)
    finally:
        await adapter.close()

    accent, speed = _persona_parts(persona)
    normalized_events = _normalize_repair_transcript_events(normalized_events)
    return {
        "episode_id": f"{overlay['speech_overlay_id']}:{mode}:{persona}:{agent}:{model}",
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
        "audio_condition_id": _audio_condition_for_mode(mode),
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
) -> None:
    """Drive a voice/FDRC episode with real synthesized audio over the realtime session."""
    cache = _get_audio_cache()
    accent, speed = _persona_parts(persona)

    if overlay["benchmark_track"] == "full_duplex_repair_to_commit":
        initial_text = overlay.get("initial_spoken_utterance", "")
        repair_text = overlay.get("repair_utterance", "")
        initial = cache.get_or_build(initial_text, accent, speed, "interaction_stress")
        repair = cache.get_or_build(repair_text, accent, speed, "interaction_stress")
        interrupt_ms = _timeline_interrupt_ms(overlay)
        user_transcript.extend([initial_text, repair_text])
        # Drain concurrently so the repair audio can overlap the assistant's response.
        episode_started = time.perf_counter()
        drain = asyncio.create_task(
            _drain_adapter_events(adapter, server, normalized_events, assistant_transcript, failures)
        )
        await _stream_audio(
            adapter,
            initial,
            normalized_events,
            episode_started=episode_started,
            overlap=False,
        )
        await adapter.commit_audio_turn()
        elapsed = time.perf_counter() - episode_started
        await asyncio.sleep(max(0.0, interrupt_ms / 1000 - elapsed))
        if fdrc_yield_mode == "client_cancel_yield":
            normalized_events.append(
                {
                    "type": "client_cancel_response",
                    "t_ms": int((time.perf_counter() - episode_started) * 1000),
                }
            )
            await adapter.cancel_response()
        await _stream_audio(
            adapter,
            repair,
            normalized_events,
            episode_started=episode_started,
            overlap=True,
        )
        await adapter.commit_audio_turn()
        await drain
        return

    condition = MODE_TO_AUDIO_CONDITION[mode]
    text = overlay.get("spoken_utterance") or task.get("user_goal", "")
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


async def _drain_adapter_events(
    adapter: ViviAgentAdapter,
    server: MockToolServer,
    normalized_events: list[dict],
    assistant_transcript: list[str],
    failures: list[str],
) -> None:
    async for event in adapter.receive_events():
        normalized_events.append(dict(event))
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
