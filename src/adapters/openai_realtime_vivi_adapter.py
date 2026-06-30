from __future__ import annotations

import asyncio
import base64
import json
import os
import time
from typing import AsyncIterator

from .base_vivi_agent_adapter import (
    NormalizedEvent,
    TransportError,
    ViviAgentAdapter,
    connect_with_retries,
)

REALTIME_SR = 24000


class OpenAIRealtimeViviAdapter(ViviAgentAdapter):
    """OpenAI Realtime GA adapter. Streams PCM16/24 kHz audio in, receives audio,
    transcript, and tool-call events, and forwards tool results back."""

    def __init__(self, model: str = "gpt-realtime-mini", idle_timeout_s: float = 12.0, voice: str = "alloy") -> None:
        self.model = model
        self.idle_timeout_s = idle_timeout_s
        self.voice = voice
        self.websocket = None
        self._events: asyncio.Queue[NormalizedEvent | None] = asyncio.Queue()
        self._reader_task: asyncio.Task | None = None
        self._started = time.perf_counter()
        self._assistant_speaking = False
        self._send_lock = asyncio.Lock()
        # Realtime surfaces a function call across several events: the name arrives
        # first on `response.output_item.added`/`conversation.item.added`, while the
        # completed arguments arrive later on `response.function_call_arguments.done`
        # (which does not always echo the name). Track name+call_id keyed by the
        # realtime item_id so we can reassemble the call no matter which completion
        # event carries it, and dedup so we never execute the same call twice.
        self._fc_pending: dict[str, dict] = {}
        self._fc_emitted: set[str] = set()

    async def start_session(self, *, system_prompt: str, tools: list[dict]) -> None:
        if not os.getenv("OPENAI_API_KEY"):
            raise RuntimeError("OPENAI_API_KEY is required for --agent openai_realtime")
        try:
            import websockets
        except ImportError as exc:
            raise RuntimeError("The websockets package is required for --agent openai_realtime") from exc
        self._started = time.perf_counter()
        # GA Realtime: no OpenAI-Beta header (that forces the disabled beta shape).
        headers = {"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"}
        url = f"wss://api.openai.com/v1/realtime?model={self.model}"

        async def _connect():
            try:
                return await websockets.connect(url, additional_headers=headers)
            except TypeError:
                # Older websockets used `extra_headers`; retry with that name.
                return await websockets.connect(url, extra_headers=headers)

        # A DNS/connection-level failure (e.g. getaddrinfo failed) is transient
        # infrastructure noise, not a model failure: retry with backoff and, if it
        # still fails, raise TransportError so the runner records it as an
        # infrastructure error rather than a malformed model episode.
        self.websocket = await connect_with_retries(_connect)
        await self._send(
            {
                "type": "session.update",
                "session": {
                    "type": "realtime",
                    "instructions": system_prompt,
                    "tools": [self._ga_tool(tool) for tool in tools],
                    "tool_choice": "auto",
                    "output_modalities": ["audio"],
                    "audio": {
                        "input": {
                            "format": {"type": "audio/pcm", "rate": REALTIME_SR},
                            "turn_detection": None,
                            "transcription": {"model": "gpt-4o-mini-transcribe"},
                        },
                        "output": {
                            "format": {"type": "audio/pcm", "rate": REALTIME_SR},
                            "voice": self.voice,
                        },
                    },
                },
            }
        )
        self._reader_task = asyncio.create_task(self._reader_loop())

    @staticmethod
    def _ga_tool(tool: dict) -> dict:
        # Realtime function tools take type/name/description/parameters (no `strict`).
        return {
            "type": "function",
            "name": tool["name"],
            "description": tool.get("description", ""),
            "parameters": tool["parameters"],
        }

    async def send_text(self, text: str) -> None:
        await self._send(
            {
                "type": "conversation.item.create",
                "item": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": text}],
                },
            },
            tolerate_drop=True,
        )
        await self._send({"type": "response.create"}, tolerate_drop=True)

    async def send_audio_chunk(self, audio_bytes: bytes, timestamp_ms: int) -> None:
        await self._send(
            {
                "type": "input_audio_buffer.append",
                "audio": base64.b64encode(audio_bytes).decode("ascii"),
            },
            tolerate_drop=True,
        )

    async def commit_audio_turn(self) -> None:
        await self._send({"type": "input_audio_buffer.commit"}, tolerate_drop=True)
        await self._send({"type": "response.create"}, tolerate_drop=True)

    async def receive_events(self) -> AsyncIterator[NormalizedEvent]:
        while True:
            try:
                event = await asyncio.wait_for(self._events.get(), timeout=self.idle_timeout_s)
            except asyncio.TimeoutError:
                # The realtime stream went quiet; treat as end of the turn so the
                # orchestrator does not block forever waiting for a close signal.
                break
            if event is None:
                break
            yield event

    async def send_tool_result(self, call_id: str, result: dict) -> None:
        await self._send(
            {
                "type": "conversation.item.create",
                "item": {
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": json.dumps(result, ensure_ascii=False),
                },
            },
            tolerate_drop=True,
        )
        await self._send({"type": "response.create"}, tolerate_drop=True)

    async def cancel_response(self) -> None:
        await self._send({"type": "response.cancel"}, tolerate_drop=True)

    async def close(self) -> None:
        if self._reader_task:
            self._reader_task.cancel()
        if self.websocket:
            try:
                await self.websocket.close()
            except Exception:
                # A dropped realtime socket may already be effectively closed.
                # Teardown must not abort the batch after the episode is recorded.
                pass
        await self._events.put(None)

    async def _send(self, payload: dict, *, tolerate_drop: bool = False) -> None:
        if self.websocket is None:
            raise RuntimeError("Realtime session has not started")
        # The sender (audio turns) and the drainer (tool results) both write to the
        # one websocket concurrently during FDRC; serialize frames with a lock.
        async with self._send_lock:
            try:
                await self.websocket.send(json.dumps(payload, ensure_ascii=False))
            except Exception as exc:
                if not tolerate_drop:
                    raise
                await self._events.put(
                    {"type": "session_error", "t_ms": self._t_ms(), "error": str(exc)}
                )
                await self._events.put(None)

    async def _reader_loop(self) -> None:
        try:
            async for raw in self.websocket:
                await self._events.put(self._normalize(json.loads(raw)))
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            # Tag a mid-stream connection drop distinctly from a protocol error so
            # downstream classification can tell infrastructure noise from a model
            # failure.
            from .base_vivi_agent_adapter import is_transport_error

            error_kind = "transport" if is_transport_error(exc) else "protocol"
            await self._events.put(
                {
                    "type": "session_error",
                    "t_ms": self._t_ms(),
                    "error": str(exc),
                    "error_kind": error_kind,
                }
            )
        finally:
            await self._events.put(None)

    def _register_function_call_item(self, item) -> None:
        """Record a function-call item's name keyed by its realtime item_id so a
        later arguments-only completion event can be resolved to a tool name."""
        if not isinstance(item, dict):
            return
        if item.get("type") != "function_call":
            return
        item_id = item.get("id")
        if not item_id:
            return
        entry = self._fc_pending.setdefault(item_id, {})
        if item.get("name"):
            entry["name"] = item["name"]
        if item.get("call_id"):
            entry["call_id"] = item["call_id"]
        # Arguments may already be present on a fully-formed item.
        if item.get("arguments"):
            entry["arguments"] = item["arguments"]

    def _function_call_from_event(self, event: dict) -> NormalizedEvent | None:
        """Reassemble a tool_call from any function-call completion event.

        Pulls name/call_id/arguments from the event itself (the
        ``response.function_call_arguments.done`` shape puts them at the top
        level) or from the nested ``item`` (the ``*.output_item.done`` /
        ``conversation.item.done`` shape), backfilling a missing name from the
        item-id registry. Returns ``None`` for non-function events, and dedups by
        call_id so the same call is never executed twice when several completion
        events describe it."""
        item = event.get("item")
        item = item if isinstance(item, dict) else {}
        item_type = item.get("type", event.get("type"))
        # The arguments-only event has no item.type; treat it as a function call.
        is_args_event = event.get("type") == "response.function_call_arguments.done"
        if not is_args_event and item.get("type") not in {None, "function_call"}:
            return None
        if not is_args_event and item.get("type") is None and "name" not in event:
            # A plain message/audio output item: not a function call.
            return None

        item_id = item.get("id") or event.get("item_id")
        registry = self._fc_pending.get(item_id, {}) if item_id else {}

        name = (
            item.get("name")
            or event.get("name")
            or registry.get("name")
        )
        call_id = (
            item.get("call_id")
            or event.get("call_id")
            or registry.get("call_id")
            or item_id
        )
        raw_args = (
            item.get("arguments")
            if item.get("arguments") is not None
            else event.get("arguments")
        )
        if raw_args is None:
            raw_args = registry.get("arguments")

        if not name:
            # Genuinely not a function call (or name never announced); skip.
            return None

        # Dedup: the model often surfaces the same call via both the
        # arguments-done event and the output-item-done event.
        dedup_key = call_id or f"{name}:{raw_args}"
        if dedup_key in self._fc_emitted:
            return None
        self._fc_emitted.add(dedup_key)
        if item_id in self._fc_pending:
            self._fc_pending.pop(item_id, None)

        try:
            args = json.loads(raw_args) if raw_args else {}
        except (TypeError, json.JSONDecodeError):
            args = {}
        return {
            "type": "tool_call",
            "t_ms": self._t_ms(),
            "tool": name,
            "args": args,
            "call_id": call_id,
        }

    def _t_ms(self) -> int:
        return int((time.perf_counter() - self._started) * 1000)

    def _normalize(self, event: dict) -> NormalizedEvent:
        event_type = event.get("type", "")
        if event_type in {"response.output_audio.delta", "response.audio.delta"}:
            if not self._assistant_speaking:
                self._assistant_speaking = True
                self._events.put_nowait({"type": "assistant_speech_start", "t_ms": self._t_ms()})
            return {"type": "assistant_audio_delta", "t_ms": self._t_ms()}
        if event_type in {"response.output_audio.done", "response.audio.done"}:
            self._assistant_speaking = False
            return {"type": "assistant_speech_stop", "t_ms": self._t_ms()}
        if event_type in {
            "response.output_audio_transcript.delta",
            "response.audio_transcript.delta",
            "response.output_text.delta",
        }:
            return {"type": "assistant_transcript_delta", "t_ms": self._t_ms(), "text": event.get("delta", "")}
        if event_type == "conversation.item.input_audio_transcription.completed":
            return {"type": "user_transcript_done", "t_ms": self._t_ms(), "text": event.get("transcript", "")}
        # Register the function-call name as soon as the item is announced, so a
        # later arguments-only `.done` event can still be resolved to a tool name.
        if event_type in {
            "response.output_item.added",
            "conversation.item.added",
            "conversation.item.created",
        }:
            self._register_function_call_item(event.get("item"))
        # Any of these can carry the completed function call (the arguments-only
        # event, or a fully-formed completed item). `_function_call_from_event`
        # reassembles name+args+call_id and dedups so the same call fires once.
        if event_type in {
            "response.function_call_arguments.done",
            "response.output_item.done",
            "conversation.item.done",
        }:
            call = self._function_call_from_event(event)
            if call is not None:
                return call
        if event_type == "input_audio_buffer.speech_started":
            return {"type": "user_speech_start", "t_ms": self._t_ms()}
        if event_type == "input_audio_buffer.speech_stopped":
            return {"type": "user_speech_stop", "t_ms": self._t_ms()}
        if event_type.endswith(".error") or event_type == "error":
            return {"type": "session_error", "t_ms": self._t_ms(), "error": json.dumps(event, ensure_ascii=False)}
        return {"type": event_type or "unknown", "t_ms": self._t_ms()}
