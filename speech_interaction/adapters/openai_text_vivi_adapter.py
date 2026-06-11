from __future__ import annotations

import asyncio
import json
import os
import time
from typing import AsyncIterator

from .base_vivi_agent_adapter import NormalizedEvent, ViviAgentAdapter


class OpenAITextViviAdapter(ViviAgentAdapter):
    def __init__(self, model: str = "gpt-4o-mini", idle_timeout_s: float = 1.0) -> None:
        self.model = model
        self.idle_timeout_s = idle_timeout_s
        self.system_prompt = ""
        self.tools: list[dict] = []
        self.messages: list[dict] = []
        self._pending_call_ids: set[str] = set()
        self._events: asyncio.Queue[NormalizedEvent | None] = asyncio.Queue()
        self._started = time.perf_counter()

    async def start_session(self, *, system_prompt: str, tools: list[dict]) -> None:
        self.system_prompt = system_prompt
        self.tools = tools
        self.messages = [{"role": "system", "content": system_prompt}]
        self._started = time.perf_counter()

    async def send_text(self, text: str) -> None:
        self.messages.append({"role": "user", "content": text})
        await asyncio.to_thread(self._call_openai_once)

    async def send_audio_chunk(self, audio_bytes: bytes, timestamp_ms: int) -> None:
        raise NotImplementedError("OpenAITextViviAdapter does not accept audio chunks")

    async def receive_events(self) -> AsyncIterator[NormalizedEvent]:
        while True:
            try:
                event = await asyncio.wait_for(
                    self._events.get(), timeout=self.idle_timeout_s
                )
            except asyncio.TimeoutError:
                break
            if event is None:
                break
            yield event

    async def send_tool_result(self, call_id: str, result: dict) -> None:
        self.messages.append(
            {
                "role": "tool",
                "tool_call_id": call_id,
                "content": json.dumps(result, ensure_ascii=False),
            }
        )
        self._pending_call_ids.discard(call_id)
        if self._pending_call_ids:
            return
        await asyncio.to_thread(self._call_openai_once)

    async def close(self) -> None:
        await self._events.put(None)

    def _t_ms(self) -> int:
        return int((time.perf_counter() - self._started) * 1000)

    def _call_openai_once(self) -> None:
        if not os.getenv("OPENAI_API_KEY"):
            raise RuntimeError("OPENAI_API_KEY is required for --agent openai_text")
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError("The openai package is required for --agent openai_text") from exc
        client = OpenAI()
        if hasattr(client, "responses"):
            response = client.responses.create(
                model=self.model,
                input=self._responses_input(),
                tools=self.tools,
            )
            self._parse_responses_output(response)
        else:
            response = client.chat.completions.create(
                model=self.model,
                messages=self.messages,
                tools=[{"type": "function", "function": self._chat_tool(tool)} for tool in self.tools],
                tool_choice="auto",
            )
            self._parse_chat_output(response)

    def _responses_input(self) -> list[dict]:
        rows = []
        for message in self.messages:
            if "responses_item" in message:
                # Replay the model's own function_call so the matching
                # function_call_output is accepted by the Responses API.
                rows.append(message["responses_item"])
            elif message["role"] == "tool":
                rows.append(
                    {
                        "type": "function_call_output",
                        "call_id": message["tool_call_id"],
                        "output": message["content"],
                    }
                )
            else:
                rows.append({"role": message["role"], "content": message["content"]})
        return rows

    def _parse_responses_output(self, response) -> None:
        for item in getattr(response, "output", []) or []:
            item_type = getattr(item, "type", None) or item.get("type")
            if item_type == "function_call":
                name = getattr(item, "name", None) or item.get("name")
                call_id = getattr(item, "call_id", None) or item.get("call_id")
                args_raw = getattr(item, "arguments", None) or item.get("arguments") or "{}"
                self.messages.append(
                    {
                        "role": "assistant",
                        "responses_item": {
                            "type": "function_call",
                            "call_id": call_id,
                            "name": name,
                            "arguments": args_raw,
                        },
                    }
                )
                if call_id:
                    self._pending_call_ids.add(call_id)
                self._events.put_nowait(
                    {
                        "type": "tool_call",
                        "t_ms": self._t_ms(),
                        "tool": name,
                        "args": json.loads(args_raw),
                        "call_id": call_id,
                    }
                )
            elif item_type == "message":
                text = self._extract_response_text(item)
                if text:
                    self.messages.append({"role": "assistant", "content": text})
                    self._events.put_nowait(
                        {"type": "assistant_text_delta", "t_ms": self._t_ms(), "text": text}
                    )

    def _extract_response_text(self, item) -> str:
        parts = getattr(item, "content", None) or item.get("content", [])
        values = []
        for part in parts:
            text = getattr(part, "text", None) or part.get("text")
            if text:
                values.append(text)
        return "".join(values)

    def _parse_chat_output(self, response) -> None:
        message = response.choices[0].message
        if getattr(message, "content", None):
            self._events.put_nowait(
                {"type": "assistant_text_delta", "t_ms": self._t_ms(), "text": message.content}
            )
        for call in getattr(message, "tool_calls", []) or []:
            self._pending_call_ids.add(call.id)
            self._events.put_nowait(
                {
                    "type": "tool_call",
                    "t_ms": self._t_ms(),
                    "tool": call.function.name,
                    "args": json.loads(call.function.arguments or "{}"),
                    "call_id": call.id,
                }
            )

    def _chat_tool(self, tool: dict) -> dict:
        return {
            "name": tool["name"],
            "description": tool.get("description", ""),
            "parameters": tool["parameters"],
        }
