from __future__ import annotations

import asyncio
import base64
import json
import os
import time
from typing import AsyncIterator

from .base_vivi_agent_adapter import NormalizedEvent, ViviAgentAdapter

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
        try:
            self.websocket = await websockets.connect(url, additional_headers=headers)
        except TypeError:
            self.websocket = await websockets.connect(url, extra_headers=headers)
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
            }
        )
        await self._send({"type": "response.create"})

    async def send_audio_chunk(self, audio_bytes: bytes, timestamp_ms: int) -> None:
        await self._send(
            {
                "type": "input_audio_buffer.append",
                "audio": base64.b64encode(audio_bytes).decode("ascii"),
            }
        )

    async def commit_audio_turn(self) -> None:
        await self._send({"type": "input_audio_buffer.commit"})
        await self._send({"type": "response.create"})

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
            }
        )
        await self._send({"type": "response.create"})

    async def cancel_response(self) -> None:
        await self._send({"type": "response.cancel"})

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

    async def _send(self, payload: dict) -> None:
        if self.websocket is None:
            raise RuntimeError("Realtime session has not started")
        # The sender (audio turns) and the drainer (tool results) both write to the
        # one websocket concurrently during FDRC; serialize frames with a lock.
        async with self._send_lock:
            await self.websocket.send(json.dumps(payload, ensure_ascii=False))

    async def _reader_loop(self) -> None:
        try:
            async for raw in self.websocket:
                await self._events.put(self._normalize(json.loads(raw)))
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            await self._events.put({"type": "session_error", "t_ms": self._t_ms(), "error": str(exc)})
        finally:
            await self._events.put(None)

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
        if event_type in {"response.function_call_arguments.done", "response.output_item.done"}:
            item = event.get("item", event)
            if item.get("type") in {None, "function_call"} and item.get("name"):
                return {
                    "type": "tool_call",
                    "t_ms": self._t_ms(),
                    "tool": item.get("name"),
                    "args": json.loads(item.get("arguments") or "{}"),
                    "call_id": item.get("call_id") or item.get("id"),
                }
        if event_type == "input_audio_buffer.speech_started":
            return {"type": "user_speech_start", "t_ms": self._t_ms()}
        if event_type == "input_audio_buffer.speech_stopped":
            return {"type": "user_speech_stop", "t_ms": self._t_ms()}
        if event_type.endswith(".error") or event_type == "error":
            return {"type": "session_error", "t_ms": self._t_ms(), "error": json.dumps(event, ensure_ascii=False)}
        return {"type": event_type or "unknown", "t_ms": self._t_ms()}
