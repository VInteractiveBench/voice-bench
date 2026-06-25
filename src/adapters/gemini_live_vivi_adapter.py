# src/adapters/gemini_live_vivi_adapter.py
from __future__ import annotations

import asyncio
import os
import time
from typing import Any, AsyncIterator

from src.audio import audio_io

from .base_vivi_agent_adapter import NormalizedEvent, ViviAgentAdapter


def _strip_unsupported(parameters: dict) -> dict:
    """Gemini accepts an OpenAPI subset: drop OpenAI-only keys and normalize the
    nullable patterns (``"type": ["string", "null"]`` / ``null`` enum members)
    that the Gemini schema validator rejects."""
    cleaned: dict = {}
    for key, value in parameters.items():
        if key in {"additionalProperties", "strict"}:
            continue
        if key == "type" and isinstance(value, list):
            non_null = [t for t in value if t != "null"]
            cleaned["type"] = non_null[0] if non_null else "null"
            if "null" in value:
                cleaned["nullable"] = True
        elif key == "enum" and isinstance(value, list):
            cleaned["enum"] = [v for v in value if v is not None]
        elif key == "properties" and isinstance(value, dict):
            cleaned[key] = {k: _strip_unsupported(v) if isinstance(v, dict) else v for k, v in value.items()}
        elif isinstance(value, dict):
            cleaned[key] = _strip_unsupported(value)
        else:
            cleaned[key] = value
    return cleaned


def to_gemini_tools(openai_schemas: list[dict]) -> list[dict]:
    declarations = [
        {
            "name": schema["name"],
            "description": schema.get("description", ""),
            "parameters": _strip_unsupported(schema.get("parameters", {})),
        }
        for schema in openai_schemas
    ]
    return [{"function_declarations": declarations}]


def normalize_gemini_message(message: Any, *, t_ms: int, speaking: bool) -> list[NormalizedEvent]:
    """Pure mapping from a Gemini Live message to NormalizedEvent list.

    `speaking` is whether assistant_speech_start has already been emitted for the
    current turn; the caller owns that flag and updates it from the returned events.
    """
    events: list[NormalizedEvent] = []

    if getattr(message, "data", None):
        if not speaking:
            events.append({"type": "assistant_speech_start", "t_ms": t_ms})
        events.append({"type": "assistant_audio_delta", "t_ms": t_ms})
        return events

    sc = getattr(message, "server_content", None)
    if sc is not None:
        out_tx = getattr(sc, "output_transcription", None)
        if out_tx is not None and getattr(out_tx, "text", None):
            events.append({"type": "assistant_transcript_delta", "t_ms": t_ms, "text": out_tx.text})
        in_tx = getattr(sc, "input_transcription", None)
        if in_tx is not None and getattr(in_tx, "text", None):
            events.append({"type": "user_transcript_done", "t_ms": t_ms, "text": in_tx.text})
        if getattr(sc, "interrupted", None):
            events.append({"type": "assistant_yielded", "t_ms": t_ms})
        if getattr(sc, "turn_complete", None):
            events.append({"type": "assistant_speech_stop", "t_ms": t_ms})

    tc = getattr(message, "tool_call", None)
    if tc is not None:
        for call in getattr(tc, "function_calls", None) or []:
            events.append({
                "type": "tool_call",
                "t_ms": t_ms,
                "tool": getattr(call, "name", ""),
                "args": dict(getattr(call, "args", {}) or {}),
                "call_id": getattr(call, "id", "") or getattr(call, "name", ""),
            })

    return events


GEMINI_INPUT_SR = 16000


class GeminiLiveViviAdapter(ViviAgentAdapter):
    """Gemini Live adapter. Streams PCM16/16 kHz audio in, normalizes audio,
    transcript and tool-call messages, forwards tool results back.

    `session` may be injected for tests; otherwise a real google-genai Live
    session is opened in `start_session`.
    """

    def __init__(self, model: str = "gemini-2.0-flash-live-001", *, idle_timeout_s: float = 12.0, session=None) -> None:
        self.model = model
        self.idle_timeout_s = idle_timeout_s
        self._session = session
        self._injected = session is not None
        self._cm = None
        self._events: asyncio.Queue[NormalizedEvent | None] = asyncio.Queue()
        self._reader_task: asyncio.Task | None = None
        self._started = time.perf_counter()
        self._speaking = False

    async def start_session(self, *, system_prompt: str, tools: list[dict]) -> None:
        self._started = time.perf_counter()
        if self._session is None:
            if not os.getenv("GOOGLE_API_KEY"):
                raise RuntimeError("GEMINI_API_LIVE/GOOGLE_API_KEY is required for --agent gemini_live")
            from google import genai
            client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])
            config = {
                "system_instruction": system_prompt,
                "tools": to_gemini_tools(tools),
                "response_modalities": ["AUDIO"],
                "input_audio_transcription": {},
                "output_audio_transcription": {},
            }
            self._cm = client.aio.live.connect(model=self.model, config=config)
            self._session = await self._cm.__aenter__()
        self._reader_task = asyncio.create_task(self._reader_loop())

    async def send_text(self, text: str) -> None:
        await self._session.send_realtime_input(text=text)

    async def send_audio_chunk(self, audio_bytes: bytes, timestamp_ms: int) -> None:
        floats = audio_io.pcm16_to_float(audio_bytes)
        resampled = audio_io.resample(floats, audio_io.TARGET_SR, GEMINI_INPUT_SR)
        pcm16 = audio_io.float_to_pcm16(resampled)
        await self._session.send_realtime_input(
            audio={"data": pcm16, "mime_type": f"audio/pcm;rate={GEMINI_INPUT_SR}"}
        )

    async def commit_audio_turn(self) -> None:
        # Signal end-of-audio so automatic VAD finalizes the turn. Without this the
        # model never responds to short/clean turns (it keeps waiting for more audio).
        await self._session.send_realtime_input(audio_stream_end=True)

    async def cancel_response(self) -> None:
        # Gemini auto-interrupts on new input; no explicit cancel frame is sent.
        return None

    async def receive_events(self) -> AsyncIterator[NormalizedEvent]:
        while True:
            try:
                event = await asyncio.wait_for(self._events.get(), timeout=self.idle_timeout_s)
            except asyncio.TimeoutError:
                break
            if event is None:
                break
            yield event

    async def send_tool_result(self, call_id: str, result: dict) -> None:
        await self._session.send_tool_response(
            function_responses=[{"id": call_id, "name": call_id, "response": result}]
        )

    async def close(self) -> None:
        if self._reader_task:
            self._reader_task.cancel()
        if self._session is not None and not self._injected:
            try:
                await self._cm.__aexit__(None, None, None)
            except Exception:
                await self._session.close()
        await self._events.put(None)

    def _t_ms(self) -> int:
        return int((time.perf_counter() - self._started) * 1000)

    async def _reader_loop(self) -> None:
        try:
            # `session.receive()` is a per-turn generator: it ends on turn_complete.
            # Re-invoke it for each subsequent turn so multi-turn episodes (e.g. the
            # FDRC repair turn) aren't dropped. Re-invoking blocks until the next
            # turn's input arrives, so this does not busy-spin.
            while True:
                async for message in self._session.receive():
                    for event in normalize_gemini_message(message, t_ms=self._t_ms(), speaking=self._speaking):
                        if event["type"] == "assistant_speech_start":
                            self._speaking = True
                        elif event["type"] in {"assistant_speech_stop", "assistant_yielded"}:
                            self._speaking = False
                        await self._events.put(event)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            await self._events.put({"type": "session_error", "t_ms": self._t_ms(), "error": str(exc)})
        finally:
            await self._events.put(None)
