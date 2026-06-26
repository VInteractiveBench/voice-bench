# tests/test_gemini_live_adapter.py
from src.adapters.gemini_live_vivi_adapter import to_gemini_tools


def test_to_gemini_tools_strips_openai_only_keys():
    openai_schemas = [
        {
            "type": "function",
            "name": "climate_control",
            "description": "Set climate.",
            "parameters": {
                "type": "object",
                "properties": {"device": {"type": "string"}},
                "required": ["device"],
                "additionalProperties": False,
            },
            "strict": True,
        }
    ]
    tools = to_gemini_tools(openai_schemas)
    assert tools == [
        {
            "function_declarations": [
                {
                    "name": "climate_control",
                    "description": "Set climate.",
                    "parameters": {
                        "type": "object",
                        "properties": {"device": {"type": "string"}},
                        "required": ["device"],
                    },
                }
            ]
        }
    ]


def test_to_gemini_tools_normalizes_nullable_type_and_enum():
    openai_schemas = [
        {
            "type": "function",
            "name": "climate_control",
            "description": "Set climate.",
            "parameters": {
                "type": "object",
                "properties": {
                    "level": {"type": ["integer", "null"]},
                    "position": {
                        "type": ["string", "null"],
                        "enum": ["all", "driver", None],
                    },
                },
                "required": ["level"],
            },
        }
    ]
    props = to_gemini_tools(openai_schemas)[0]["function_declarations"][0]["parameters"]["properties"]
    # Gemini accepts only a single scalar type string + a `nullable` flag.
    assert props["level"] == {"type": "integer", "nullable": True}
    # null is dropped from enum; the type collapses to the non-null member.
    assert props["position"] == {"type": "string", "nullable": True, "enum": ["all", "driver"]}


def test_to_gemini_tools_empty():
    assert to_gemini_tools([]) == [{"function_declarations": []}]


from types import SimpleNamespace
from src.adapters.gemini_live_vivi_adapter import normalize_gemini_message


def _msg(**kw):
    base = dict(data=None, server_content=None, tool_call=None)
    base.update(kw)
    return SimpleNamespace(**base)


def test_audio_first_chunk_emits_speech_start_then_delta():
    events = normalize_gemini_message(_msg(data=b"\x00\x01"), t_ms=120, speaking=False)
    assert [e["type"] for e in events] == ["assistant_speech_start", "assistant_audio_delta"]
    assert events[0]["t_ms"] == 120


def test_audio_subsequent_chunk_emits_only_delta():
    events = normalize_gemini_message(_msg(data=b"\x00\x01"), t_ms=140, speaking=True)
    assert [e["type"] for e in events] == ["assistant_audio_delta"]


def test_output_transcription_delta():
    sc = SimpleNamespace(output_transcription=SimpleNamespace(text="xin chào"),
                         input_transcription=None, interrupted=None, turn_complete=None)
    events = normalize_gemini_message(_msg(server_content=sc), t_ms=200, speaking=True)
    assert events == [{"type": "assistant_transcript_delta", "t_ms": 200, "text": "xin chào"}]


def test_input_transcription_done():
    sc = SimpleNamespace(input_transcription=SimpleNamespace(text="24 độ"),
                         output_transcription=None, interrupted=None, turn_complete=None)
    events = normalize_gemini_message(_msg(server_content=sc), t_ms=300, speaking=True)
    assert events == [{"type": "user_transcript_done", "t_ms": 300, "text": "24 độ"}]


def test_interrupted_emits_yielded():
    sc = SimpleNamespace(interrupted=True, input_transcription=None,
                         output_transcription=None, turn_complete=None)
    events = normalize_gemini_message(_msg(server_content=sc), t_ms=350, speaking=True)
    assert events == [{"type": "assistant_yielded", "t_ms": 350}]


def test_turn_complete_emits_speech_stop():
    sc = SimpleNamespace(turn_complete=True, interrupted=None,
                         input_transcription=None, output_transcription=None)
    events = normalize_gemini_message(_msg(server_content=sc), t_ms=400, speaking=True)
    assert events == [{"type": "assistant_speech_stop", "t_ms": 400}]


def test_tool_call_maps_function_calls():
    tc = SimpleNamespace(function_calls=[
        SimpleNamespace(id="call_1", name="climate_control", args={"device": "temp", "value": 24})
    ])
    events = normalize_gemini_message(_msg(tool_call=tc), t_ms=500, speaking=True)
    assert events == [{
        "type": "tool_call", "t_ms": 500, "tool": "climate_control",
        "args": {"device": "temp", "value": 24}, "call_id": "call_1",
    }]


import asyncio
from src.adapters.gemini_live_vivi_adapter import GeminiLiveViviAdapter


def test_realtime_close_swallows_websocket_drop():
    from src.adapters.openai_realtime_vivi_adapter import OpenAIRealtimeViviAdapter

    adapter = OpenAIRealtimeViviAdapter()

    class _DroppedWS:
        async def close(self):
            raise RuntimeError("no close frame received or sent")

    adapter.websocket = _DroppedWS()
    asyncio.run(adapter.close())


class _FakeSession:
    def __init__(self, messages):
        self._messages = messages
        self.sent_audio = []
        self.tool_responses = []
        self.closed = False
        self._recv_calls = 0

    async def send_realtime_input(self, *, audio=None, **kw):
        self.sent_audio.append(audio)

    async def send_tool_response(self, *, function_responses):
        self.tool_responses.append(function_responses)

    async def receive(self):
        # Real `receive()` is per-turn; the reader loop re-invokes it. Yield the
        # scripted turn once, then end the loop cleanly on the next call.
        self._recv_calls += 1
        if self._recv_calls > 1:
            raise asyncio.CancelledError
        for m in self._messages:
            yield m

    async def close(self):
        self.closed = True


def test_adapter_drains_messages_into_normalized_events():
    from types import SimpleNamespace
    msgs = [
        SimpleNamespace(data=b"\x00\x01", server_content=None, tool_call=None),
        SimpleNamespace(
            data=None,
            server_content=SimpleNamespace(
                turn_complete=True, interrupted=None,
                input_transcription=None, output_transcription=None,
            ),
            tool_call=None,
        ),
    ]
    adapter = GeminiLiveViviAdapter(model="gemini-x", session=_FakeSession(msgs))

    async def run():
        await adapter.start_session(system_prompt="sys", tools=[])
        return [e async for e in adapter.receive_events()]

    events = asyncio.run(run())
    types = [e["type"] for e in events]
    assert "assistant_speech_start" in types
    assert "assistant_speech_stop" in types
