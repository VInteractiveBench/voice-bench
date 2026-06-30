# tests/test_openai_realtime_adapter.py
"""Static unit tests for the OpenAI Realtime adapter (no network).

Covers the two hardening fixes:
  * Problem 1 - connection-level (DNS/refused/timeout) errors are classified as
    TransportError and retried with backoff, distinct from model/protocol errors.
  * Problem 2 - function/tool-call parsing across every realtime completion event
    shape (arguments-only `.done`, completed output item, conversation item),
    including name backfill from the item-id registry and call dedup.
"""
from __future__ import annotations

import asyncio
import socket

import pytest

from src.adapters.base_vivi_agent_adapter import (
    TransportError,
    connect_with_retries,
    is_transport_error,
)
from src.adapters.openai_realtime_vivi_adapter import OpenAIRealtimeViviAdapter


# --------------------------------------------------------------------------- #
# Problem 1: transport-error classification + connection retry/backoff
# --------------------------------------------------------------------------- #


def test_is_transport_error_recognizes_gaierror():
    exc = socket.gaierror(11001, "getaddrinfo failed")
    assert is_transport_error(exc) is True


def test_is_transport_error_recognizes_windows_11001_message():
    # The realtime stack often wraps gaierror in a generic OSError whose message
    # carries the Windows WSAHOST_NOT_FOUND code.
    exc = OSError("[Errno 11001] getaddrinfo failed")
    assert is_transport_error(exc) is True


def test_is_transport_error_follows_cause_chain():
    cause = socket.gaierror(11001, "getaddrinfo failed")
    wrapper = RuntimeError("connection handshake failed")
    wrapper.__cause__ = cause
    assert is_transport_error(wrapper) is True


def test_is_transport_error_recognizes_connection_refused_and_reset():
    assert is_transport_error(ConnectionRefusedError("connection refused")) is True
    assert is_transport_error(ConnectionResetError("connection reset")) is True
    assert is_transport_error(TimeoutError("timed out")) is True


def test_is_transport_error_rejects_model_and_auth_errors():
    # A protocol/model error must NOT be classified as transport (so it is not
    # silently retried or excused as infrastructure noise).
    assert is_transport_error(ValueError("invalid tool schema")) is False
    assert is_transport_error(RuntimeError("invalid_api_key")) is False
    assert is_transport_error(KeyError("name")) is False


def test_connect_with_retries_retries_transport_then_succeeds():
    attempts = {"n": 0}
    slept: list[float] = []

    async def connect():
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise socket.gaierror(11001, "getaddrinfo failed")
        return "websocket"

    async def fake_sleep(d):
        slept.append(d)

    result = asyncio.run(
        connect_with_retries(connect, attempts=3, base_delay_s=0.5, sleep=fake_sleep)
    )
    assert result == "websocket"
    assert attempts["n"] == 3
    # Exponential backoff between the two failed attempts: 0.5, then 1.0.
    assert slept == [0.5, 1.0]


def test_connect_with_retries_exhausts_and_raises_transport_error():
    async def connect():
        raise socket.gaierror(11001, "getaddrinfo failed")

    async def fake_sleep(d):
        return None

    with pytest.raises(TransportError) as exc_info:
        asyncio.run(connect_with_retries(connect, attempts=3, sleep=fake_sleep))
    # The original gaierror is chained for diagnosis.
    assert isinstance(exc_info.value.__cause__, socket.gaierror)
    assert is_transport_error(exc_info.value) is True


def test_connect_with_retries_does_not_retry_model_errors():
    attempts = {"n": 0}

    async def connect():
        attempts["n"] += 1
        raise ValueError("invalid tool schema")

    async def fake_sleep(d):
        return None

    with pytest.raises(ValueError):
        asyncio.run(connect_with_retries(connect, attempts=3, sleep=fake_sleep))
    # Non-transport errors propagate on the first attempt, no retries.
    assert attempts["n"] == 1


def test_reader_loop_tags_transport_drop_distinctly():
    adapter = OpenAIRealtimeViviAdapter()

    class _DroppedWS:
        def __aiter__(self):
            return self

        async def __anext__(self):
            raise ConnectionResetError("connection reset by peer")

    adapter.websocket = _DroppedWS()

    async def run():
        await adapter._reader_loop()
        return await adapter._events.get()

    event = asyncio.run(run())
    assert event["type"] == "session_error"
    assert event["error_kind"] == "transport"


def test_reader_loop_tags_protocol_error_distinctly():
    adapter = OpenAIRealtimeViviAdapter()

    class _BadProtocolWS:
        def __aiter__(self):
            return self

        async def __anext__(self):
            raise ValueError("unexpected frame")

    adapter.websocket = _BadProtocolWS()

    async def run():
        await adapter._reader_loop()
        return await adapter._events.get()

    event = asyncio.run(run())
    assert event["type"] == "session_error"
    assert event["error_kind"] == "protocol"


# --------------------------------------------------------------------------- #
# Problem 2: tool/function-call parsing across realtime event shapes
# --------------------------------------------------------------------------- #


def test_function_call_arguments_done_with_inline_name():
    adapter = OpenAIRealtimeViviAdapter()
    event = adapter._normalize(
        {
            "type": "response.function_call_arguments.done",
            "call_id": "call_abc",
            "name": "light_control",
            "arguments": '{"device": "ambient", "value": "bright"}',
        }
    )
    assert event["type"] == "tool_call"
    assert event["tool"] == "light_control"
    assert event["args"] == {"device": "ambient", "value": "bright"}
    assert event["call_id"] == "call_abc"


def test_function_call_arguments_done_backfills_name_from_added_item():
    """The crux of the low-capture bug: the arguments-only `.done` event does not
    always echo the function name. The name must be recovered from the earlier
    `response.output_item.added` item keyed by item_id."""
    adapter = OpenAIRealtimeViviAdapter()
    # Name announced when the item is added.
    adapter._normalize(
        {
            "type": "response.output_item.added",
            "item": {
                "id": "item_1",
                "type": "function_call",
                "name": "commit_intent",
                "call_id": "call_xyz",
            },
        }
    )
    # Arguments complete later WITHOUT a name on the event.
    event = adapter._normalize(
        {
            "type": "response.function_call_arguments.done",
            "item_id": "item_1",
            "call_id": "call_xyz",
            "arguments": '{"slot": "temperature", "value": 24}',
        }
    )
    assert event["type"] == "tool_call"
    assert event["tool"] == "commit_intent"
    assert event["args"] == {"slot": "temperature", "value": 24}
    assert event["call_id"] == "call_xyz"


def test_function_call_via_output_item_done_only():
    """Some responses surface the call only as a completed output item (no separate
    arguments-done event). That path must also produce a tool_call."""
    adapter = OpenAIRealtimeViviAdapter()
    event = adapter._normalize(
        {
            "type": "response.output_item.done",
            "item": {
                "id": "item_2",
                "type": "function_call",
                "name": "commit_intent",
                "call_id": "call_only_item",
                "arguments": '{"slot": "fan", "value": 3}',
            },
        }
    )
    assert event["type"] == "tool_call"
    assert event["tool"] == "commit_intent"
    assert event["args"] == {"slot": "fan", "value": 3}
    assert event["call_id"] == "call_only_item"


def test_function_call_via_conversation_item_done():
    adapter = OpenAIRealtimeViviAdapter()
    event = adapter._normalize(
        {
            "type": "conversation.item.done",
            "item": {
                "id": "item_3",
                "type": "function_call",
                "name": "commit_intent",
                "call_id": "call_conv",
                "arguments": "{}",
            },
        }
    )
    assert event["type"] == "tool_call"
    assert event["tool"] == "commit_intent"
    assert event["call_id"] == "call_conv"


def test_same_call_emitted_once_across_duplicate_completion_events():
    """A call frequently arrives via BOTH the arguments-done event and the
    output-item-done event. It must execute exactly once (dedup by call_id)."""
    adapter = OpenAIRealtimeViviAdapter()
    adapter._normalize(
        {
            "type": "response.output_item.added",
            "item": {"id": "item_4", "type": "function_call", "name": "commit_intent", "call_id": "call_dup"},
        }
    )
    first = adapter._normalize(
        {
            "type": "response.function_call_arguments.done",
            "item_id": "item_4",
            "call_id": "call_dup",
            "arguments": '{"x": 1}',
        }
    )
    second = adapter._normalize(
        {
            "type": "response.output_item.done",
            "item": {
                "id": "item_4",
                "type": "function_call",
                "name": "commit_intent",
                "call_id": "call_dup",
                "arguments": '{"x": 1}',
            },
        }
    )
    assert first["type"] == "tool_call"
    # The duplicate completion is squashed to a benign non-tool_call event.
    assert second["type"] != "tool_call"


def test_message_output_item_done_is_not_a_tool_call():
    """A plain audio/message output item (the common case) must NOT be mistaken
    for a function call."""
    adapter = OpenAIRealtimeViviAdapter()
    event = adapter._normalize(
        {
            "type": "response.output_item.done",
            "item": {
                "id": "item_5",
                "type": "message",
                "role": "assistant",
                "content": [{"type": "audio"}],
            },
        }
    )
    assert event["type"] != "tool_call"


def test_malformed_arguments_default_to_empty_dict():
    adapter = OpenAIRealtimeViviAdapter()
    event = adapter._normalize(
        {
            "type": "response.function_call_arguments.done",
            "call_id": "call_bad",
            "name": "commit_intent",
            "arguments": "{not json",
        }
    )
    assert event["type"] == "tool_call"
    assert event["args"] == {}
