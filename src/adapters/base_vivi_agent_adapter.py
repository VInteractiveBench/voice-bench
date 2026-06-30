from __future__ import annotations

import asyncio
import socket
from abc import ABC, abstractmethod
from typing import AsyncIterator, Awaitable, Callable, TypedDict, TypeVar


class TransportError(RuntimeError):
    """A connection/transport-level failure that never reached the model.

    Raised for DNS resolution failures (``socket.gaierror``), connection
    refused/reset, and connect timeouts. The orchestrator/runner treats this
    DISTINCTLY from a model or protocol error: a network death is an
    infrastructure problem (the episode never reached the API), not a model
    failure, so it must not be scored as if the model produced a bad turn.
    """


def is_transport_error(exc: BaseException) -> bool:
    """True if ``exc`` is a connection/transport-level error (DNS, refused,
    reset, connect timeout) rather than a model/protocol error.

    Matches by exception type where possible and falls back to substring
    matching on the message, because the realtime/websocket stacks wrap the
    underlying ``OSError``/``gaierror`` in library-specific exception types
    (e.g. ``websockets`` ``InvalidURI``-adjacent connection errors) whose
    ``__cause__`` is the real ``gaierror``.
    """
    seen: set[int] = set()
    cur: BaseException | None = exc
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        if isinstance(cur, socket.gaierror):
            return True
        if isinstance(cur, (ConnectionError, TimeoutError, asyncio.TimeoutError)):
            return True
        if isinstance(cur, OSError):
            # getaddrinfo failures, connection refused/reset/aborted surface as
            # OSError subclasses or bare OSError with these errno-ish messages.
            msg = str(cur).lower()
            if any(
                token in msg
                for token in (
                    "getaddrinfo failed",
                    "name or service not known",
                    "temporary failure in name resolution",
                    "connection refused",
                    "connection reset",
                    "connection aborted",
                    "network is unreachable",
                    "no route to host",
                    "timed out",
                )
            ):
                return True
        text = str(cur).lower()
        if any(
            token in text
            for token in (
                "getaddrinfo failed",
                "name or service not known",
                "temporary failure in name resolution",
                "11001",  # Windows WSAHOST_NOT_FOUND
            )
        ):
            return True
        cur = cur.__cause__ or cur.__context__
    return False


def is_account_error(exc: BaseException) -> bool:
    """True if ``exc`` is an account/billing/auth-level rejection (quota exhausted,
    invalid key, rate limit) rather than a model or transport failure.

    Like a transport death, the model was never measured — the provider rejected the
    request at the account gate (e.g. websocket close ``1013 insufficient_quota``,
    HTTP 401/403/429). The runner records these as infrastructure errors excluded from
    the validity denominator so they are not scored as model failures.
    """
    seen: set[int] = set()
    cur: BaseException | None = exc
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        text = str(cur).lower()
        if any(
            token in text
            for token in (
                "insufficient_quota",
                "insufficient quota",
                "exceeded your current quota",
                "invalid_api_key",
                "invalid api key",
                "incorrect api key",
                "unauthorized",
                "permission_denied",
                "rate_limit",
                "rate limit",
                "too many requests",
                " 401",
                " 403",
                " 429",
                "1013",  # websocket close code: try again later / quota
            )
        ):
            return True
        cur = cur.__cause__ or cur.__context__
    return False


_T = TypeVar("_T")


async def connect_with_retries(
    connect: Callable[[], Awaitable[_T]],
    *,
    attempts: int = 3,
    base_delay_s: float = 0.5,
    max_delay_s: float = 4.0,
    sleep=asyncio.sleep,
) -> _T:
    """Run ``connect()`` with bounded retry-and-backoff on transport errors only.

    A DNS/connection-level failure is retried (the host may resolve on the next
    attempt, or a transient refusal may clear) up to ``attempts`` times with
    exponential backoff. After the final attempt the underlying error is
    re-raised wrapped in :class:`TransportError` so callers can classify it as
    infrastructure rather than a model failure. Non-transport errors (auth,
    protocol, bad request) are NOT retried and propagate immediately.
    """
    last_exc: BaseException | None = None
    for attempt in range(1, attempts + 1):
        try:
            return await connect()
        except Exception as exc:  # noqa: BLE001 - classified below
            if not is_transport_error(exc):
                raise
            last_exc = exc
            if attempt >= attempts:
                break
            delay = min(base_delay_s * (2 ** (attempt - 1)), max_delay_s)
            await sleep(delay)
    raise TransportError(
        f"connection failed after {attempts} attempt(s): "
        f"{type(last_exc).__name__}: {last_exc}"
    ) from last_exc


class NormalizedEvent(TypedDict, total=False):
    type: str
    t_ms: int
    text: str
    tool: str
    args: dict
    call_id: str
    result: dict
    error: str
    error_kind: str
    chunk_id: str
    duration_ms: int
    source_type: str
    overlap: bool


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

    async def cancel_response(self) -> None:
        """Ask the provider to stop the active assistant response if supported."""
        return None

    @abstractmethod
    async def close(self) -> None:
        ...
