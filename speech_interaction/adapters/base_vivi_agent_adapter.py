from __future__ import annotations

from abc import ABC, abstractmethod
from typing import AsyncIterator, TypedDict


class NormalizedEvent(TypedDict, total=False):
    type: str
    t_ms: int
    text: str
    tool: str
    args: dict
    call_id: str
    result: dict
    error: str


class ViviAgentAdapter(ABC):
    @abstractmethod
    async def start_session(self, *, system_prompt: str, tools: list[dict]) -> None:
        ...

    @abstractmethod
    async def send_text(self, text: str) -> None:
        ...

    @abstractmethod
    async def send_audio_chunk(self, audio_bytes: bytes, timestamp_ms: int) -> None:
        ...

    @abstractmethod
    async def receive_events(self) -> AsyncIterator[NormalizedEvent]:
        ...

    @abstractmethod
    async def send_tool_result(self, call_id: str, result: dict) -> None:
        ...

    async def commit_audio_turn(self) -> None:
        """End a streamed-audio turn: commit the input buffer and ask for a response.

        Default no-op. Text adapters drive responses inside `send_text`; only the
        realtime adapter, which streams raw audio chunks, needs an explicit commit.
        """
        return None

    @abstractmethod
    async def close(self) -> None:
        ...
