# Gemini Live adapter + FDRC Leaderboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cho phép chạy benchmark FDRC bằng Gemini Live (ngoài OpenAI Realtime) với key trong `.env`, và so sánh các model qua một bảng leaderboard trên dashboard.

**Architecture:** Thêm một `GeminiLiveViviAdapter` tuân thủ đúng interface `ViviAgentAdapter` để cắm vào orchestrator/evaluator sẵn có mà không sửa core. Mọi call SDK được cô lập trong adapter; phần chuyển tool-schema và normalize event tách thành hàm thuần để test offline. Backend thêm một endpoint leaderboard chỉ đọc lại metric đã có; frontend thêm một tab bảng so sánh.

**Tech Stack:** Python 3.12, `google-genai` (Live API), pytest 9.x, FastAPI, vanilla JS (UMD helpers + Node test runner).

---

## File Structure

- Create: `src/adapters/gemini_live_vivi_adapter.py` — adapter Gemini Live + 2 hàm thuần `to_gemini_tools`, `normalize_gemini_message`.
- Modify: `src/adapters/__init__.py` — export adapter mới.
- Modify: `src/orchestrator/full_duplex_orchestrator.py` — `AgentName`, `provider_for_agent`, `build_adapter`, nhánh realtime gồm gemini, bỏ hardcode provider.
- Modify: `src/run_fdrc.py` — `--agent` choices + provider/model annotate theo agent.
- Modify: `pyproject.toml` — thêm dependency `google-genai`.
- Modify: `src/dashboard/service.py` — thêm `DashboardStore.leaderboard()`.
- Modify: `src/dashboard/app.py` — route `GET /api/leaderboard`.
- Modify: `src/dashboard/static/helpers.js` — hàm thuần `leaderboardRow`.
- Modify: `src/dashboard/static/helpers.test.cjs` — test cho `leaderboardRow`.
- Modify: `src/dashboard/static/app.js` + `index.html` — tab `02 Leaderboard`.
- Create: `tests/test_gemini_live_adapter.py`, `tests/test_provider_routing.py`, `tests/test_leaderboard.py`.

---

## Task 1: Tổng quát hóa provider theo agent

**Files:**
- Modify: `src/orchestrator/full_duplex_orchestrator.py` (line 21 `AgentName`, line ~98 `"provider": "openai"`)
- Modify: `src/run_fdrc.py` (line ~113 `provider="openai"`)
- Test: `tests/test_provider_routing.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_provider_routing.py
from src.orchestrator.full_duplex_orchestrator import provider_for_agent


def test_provider_for_agent_maps_known_agents():
    assert provider_for_agent("openai_realtime") == "openai"
    assert provider_for_agent("openai_text") == "openai"
    assert provider_for_agent("gemini_live") == "google"


def test_provider_for_agent_unknown_returns_none():
    assert provider_for_agent("something_else") is None
    assert provider_for_agent(None) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_provider_routing.py -v`
Expected: FAIL with `ImportError: cannot import name 'provider_for_agent'`.

- [ ] **Step 3: Add `provider_for_agent` and use it**

Trong `src/orchestrator/full_duplex_orchestrator.py`, đổi dòng `AgentName = Literal["openai_text", "openai_realtime"]` thành:

```python
AgentName = Literal["openai_text", "openai_realtime", "gemini_live"]

AGENT_TO_PROVIDER: dict[str, str] = {
    "openai_text": "openai",
    "openai_realtime": "openai",
    "gemini_live": "google",
}


def provider_for_agent(agent: str | None) -> str | None:
    return AGENT_TO_PROVIDER.get(agent) if agent else None
```

Trong cùng file, đổi `"provider": "openai",` (trong dict episode) thành:

```python
        "provider": provider_for_agent(agent),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_provider_routing.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Generalize provider in run_fdrc.py**

Trong `src/run_fdrc.py`, thêm import:

```python
from src.orchestrator.full_duplex_orchestrator import provider_for_agent
```

Đổi block `annotate_episodes(...)` để dùng provider/adapter theo agent:

```python
        provider=provider_for_agent(args.agent) if args.agent else None,
```

(Giữ nguyên các tham số khác.)

- [ ] **Step 6: Run full suite to verify no regression**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_orchestrator.py tests/test_provider_routing.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/orchestrator/full_duplex_orchestrator.py src/run_fdrc.py tests/test_provider_routing.py
git commit -m "feat: derive provider from agent instead of hardcoding openai"
```

---

## Task 2: Chuyển tool-schema OpenAI → Gemini (hàm thuần)

**Files:**
- Create: `src/adapters/gemini_live_vivi_adapter.py`
- Test: `tests/test_gemini_live_adapter.py`

- [ ] **Step 1: Write the failing test**

```python
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


def test_to_gemini_tools_empty():
    assert to_gemini_tools([]) == [{"function_declarations": []}]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_gemini_live_adapter.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.adapters.gemini_live_vivi_adapter'`.

- [ ] **Step 3: Create the file with `to_gemini_tools`**

```python
# src/adapters/gemini_live_vivi_adapter.py
from __future__ import annotations


def _strip_unsupported(parameters: dict) -> dict:
    """Gemini accepts an OpenAPI subset: drop OpenAI-only keys recursively."""
    cleaned = {}
    for key, value in parameters.items():
        if key in {"additionalProperties", "strict"}:
            continue
        if key == "properties" and isinstance(value, dict):
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_gemini_live_adapter.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add src/adapters/gemini_live_vivi_adapter.py tests/test_gemini_live_adapter.py
git commit -m "feat: convert tool schema to gemini function declarations"
```

---

## Task 3: Normalize message Gemini → NormalizedEvent (hàm thuần)

**Files:**
- Modify: `src/adapters/gemini_live_vivi_adapter.py`
- Test: `tests/test_gemini_live_adapter.py`

Message Gemily Live là object duck-typed. Normalize đọc bằng `getattr` để test bằng `SimpleNamespace`.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_gemini_live_adapter.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_gemini_live_adapter.py -v`
Expected: FAIL with `ImportError: cannot import name 'normalize_gemini_message'`.

- [ ] **Step 3: Implement `normalize_gemini_message`**

Thêm vào `src/adapters/gemini_live_vivi_adapter.py`:

```python
from typing import Any

from .base_vivi_agent_adapter import NormalizedEvent


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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_gemini_live_adapter.py -v`
Expected: PASS (all tests in file).

- [ ] **Step 5: Commit**

```bash
git add src/adapters/gemini_live_vivi_adapter.py tests/test_gemini_live_adapter.py
git commit -m "feat: normalize gemini live messages to NormalizedEvent"
```

---

## Task 4: Lớp `GeminiLiveViviAdapter` + wiring

**Files:**
- Modify: `src/adapters/gemini_live_vivi_adapter.py`
- Modify: `src/adapters/__init__.py`
- Modify: `src/orchestrator/full_duplex_orchestrator.py` (`build_adapter`, nhánh realtime)
- Modify: `src/run_fdrc.py` (`--agent` choices, default model)
- Modify: `pyproject.toml`
- Test: `tests/test_gemini_live_adapter.py`

Adapter cho inject `session` giả để test wiring không cần network.

- [ ] **Step 1: Write the failing test (adapter wiring with fake session)**

```python
# append to tests/test_gemini_live_adapter.py
import asyncio
from src.adapters.gemini_live_vivi_adapter import GeminiLiveViviAdapter


class _FakeSession:
    def __init__(self, messages):
        self._messages = messages
        self.sent_audio = []
        self.tool_responses = []
        self.closed = False

    async def send_realtime_input(self, *, audio=None, **kw):
        self.sent_audio.append(audio)

    async def send_tool_response(self, *, function_responses):
        self.tool_responses.append(function_responses)

    async def receive(self):
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_gemini_live_adapter.py::test_adapter_drains_messages_into_normalized_events -v`
Expected: FAIL with `ImportError: cannot import name 'GeminiLiveViviAdapter'`.

- [ ] **Step 3: Implement the adapter class**

Thêm vào `src/adapters/gemini_live_vivi_adapter.py`:

```python
import asyncio
import os
import time
from typing import AsyncIterator

from src.audio import audio_io

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
        # Automatic VAD detects turn boundaries; nothing to commit explicitly.
        return None

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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_gemini_live_adapter.py -v`
Expected: PASS (all tests).

- [ ] **Step 5: Export + wire into build_adapter**

In `src/adapters/__init__.py` add import and `__all__` entry:

```python
from .gemini_live_vivi_adapter import GeminiLiveViviAdapter
```
(add `"GeminiLiveViviAdapter",` to `__all__`.)

In `src/orchestrator/full_duplex_orchestrator.py`, update the imports block (lines 7-11) to include `GeminiLiveViviAdapter`, then in `build_adapter` add before the final fallback:

```python
    if agent == "gemini_live":
        return GeminiLiveViviAdapter(model=model)
```

In the same file, change the realtime branch guard in `run_agent_episode` (line ~75) and tool path so gemini uses the audio path:

```python
        if agent in {"openai_realtime", "gemini_live"}:
```

- [ ] **Step 6: Wire run_fdrc.py + add dependency**

In `src/run_fdrc.py` change:

```python
    parser.add_argument("--agent", choices=["openai_realtime", "gemini_live"], default=None)
```

And make the default model provider-aware right after parsing args:

```python
    if args.agent == "gemini_live" and args.model == "gpt-realtime-mini":
        args.model = os.getenv("GEMINI_MODEL") or "gemini-2.0-flash-live-001"
```
(add `import os` at top of run_fdrc.py if missing.)

In `pyproject.toml` add to dependencies array:

```toml
    "google-genai>=1.0.0",
```

Then install:

```bash
./.venv/Scripts/python.exe -m pip install "google-genai>=1.0.0"
```

- [ ] **Step 7: Run suite + import smoke**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_gemini_live_adapter.py tests/test_orchestrator.py -v`
Then: `./.venv/Scripts/python.exe -c "from src.orchestrator.full_duplex_orchestrator import build_adapter; print(type(build_adapter('gemini_live','gemini-x')).__name__)"`
Expected: tests PASS; prints `GeminiLiveViviAdapter`.

- [ ] **Step 8: Commit**

```bash
git add src/adapters/ src/orchestrator/full_duplex_orchestrator.py src/run_fdrc.py pyproject.toml tests/test_gemini_live_adapter.py
git commit -m "feat: add gemini_live adapter and wire into runner"
```

---

## Task 5: Backend leaderboard endpoint

**Files:**
- Modify: `src/dashboard/service.py` (add `DashboardStore.leaderboard`)
- Modify: `src/dashboard/app.py` (add route)
- Test: `tests/test_leaderboard.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_leaderboard.py
import json
from pathlib import Path

from src.dashboard.service import DashboardStore


def _write_run(root: Path, run_id: str, metrics: dict, episodes: list[dict]) -> None:
    d = root / run_id
    d.mkdir(parents=True)
    (d / "metrics.json").write_text(json.dumps(metrics), encoding="utf-8")
    with (d / "episodes.jsonl").open("w", encoding="utf-8") as fh:
        for ep in episodes:
            fh.write(json.dumps(ep) + "\n")


def test_leaderboard_one_row_per_fdrc_run(tmp_path):
    ep = {
        "benchmark_track": "full_duplex_repair_to_commit",
        "provider": "google", "model": "gemini-x",
        "scores": {"final_pass": 1},
    }
    _write_run(
        tmp_path, "run_gemini",
        {"fdrc_validity_rate": 1.0, "performance_fdrc_pass_at_1": 0.5,
         "raw_fdrc_pass_at_1": 0.5, "reportability_status": "REPORTABLE_DOMAIN",
         "run_metadata": {"providers": ["google"], "models": ["gemini-x"],
                          "fdrc_yield_modes": ["native_yield"]}},
        [ep],
    )
    store = DashboardStore(tmp_path)
    rows = store.leaderboard()
    assert len(rows) == 1
    row = rows[0]
    assert row["run_id"] == "run_gemini"
    assert row["provider"] == "google"
    assert row["model"] == "gemini-x"
    assert row["fdrc_validity_rate"] == 1.0
    assert row["performance_fdrc_pass_at_1"] == 0.5


def test_leaderboard_skips_non_fdrc(tmp_path):
    _write_run(
        tmp_path, "run_text",
        {"run_metadata": {}},
        [{"benchmark_track": "text_baseline", "scores": {}}],
    )
    store = DashboardStore(tmp_path)
    assert store.leaderboard() == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_leaderboard.py -v`
Expected: FAIL with `AttributeError: 'DashboardStore' object has no attribute 'leaderboard'`.

- [ ] **Step 3: Implement `leaderboard`**

Add to `DashboardStore` in `src/dashboard/service.py` (after `list_runs`):

```python
    def leaderboard(self, track: str = "full_duplex_repair_to_commit") -> list[dict[str, Any]]:
        rows = []
        for run in self.list_runs():
            if run.get("benchmark_track") != track:
                continue
            summary = self.run_summary(run["run_id"], track=track)
            metrics = summary.get("metrics", {})
            meta = summary.get("run_metadata", {}) or {}
            rows.append({
                "run_id": run["run_id"],
                "provider": (meta.get("providers") or [None])[0],
                "model": (meta.get("models") or [None])[0],
                "yield_mode": (meta.get("fdrc_yield_modes") or [None])[0],
                "run_kind": run.get("run_kind"),
                "data_provenance": run.get("data_provenance"),
                "episode_count": summary.get("episode_count"),
                "updated_at": run.get("updated_at"),
                "reportability_status": metrics.get("reportability_status"),
                "fdrc_validity_rate": metrics.get("fdrc_validity_rate"),
                "raw_fdrc_pass_at_1": metrics.get("raw_fdrc_pass_at_1"),
                "performance_fdrc_pass_at_1": metrics.get("performance_fdrc_pass_at_1"),
                "performance_yield_latency_p50_ms": metrics.get("performance_yield_latency_p50_ms"),
                "performance_yield_latency_p95_ms": metrics.get("performance_yield_latency_p95_ms"),
                "performance_yield_latency_pass_rate": metrics.get("performance_yield_latency_pass_rate"),
                "forbidden_tool_call_rate": metrics.get("forbidden_tool_call_rate"),
                "cancel_success_rate": metrics.get("cancel_success_rate"),
                "correction_uptake_rate": metrics.get("correction_uptake_rate"),
                "old_intent_suppression_rate": metrics.get("old_intent_suppression_rate"),
            })
        return rows
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_leaderboard.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Add the route**

In `src/dashboard/app.py`, after the `/api/runs` route:

```python
    @app.get("/api/leaderboard")
    def leaderboard(track: str = "full_duplex_repair_to_commit") -> list[dict[str, Any]]:
        return store.leaderboard(track=track)
```

- [ ] **Step 6: Verify route serves**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_dashboard.py tests/test_leaderboard.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/dashboard/service.py src/dashboard/app.py tests/test_leaderboard.py
git commit -m "feat: add /api/leaderboard endpoint"
```

---

## Task 6: Frontend helper `leaderboardRow` (pure + node test)

**Files:**
- Modify: `src/dashboard/static/helpers.js` (add function + export)
- Modify: `src/dashboard/static/helpers.test.cjs`

- [ ] **Step 1: Write the failing test**

Append to `src/dashboard/static/helpers.test.cjs`:

```javascript
t("leaderboardRow formats reportable run", () => {
  const r = VB.leaderboardRow({
    run_id: "run_gemini", provider: "google", model: "gemini-x",
    yield_mode: "native_yield", episode_count: 90,
    reportability_status: "REPORTABLE_DOMAIN",
    fdrc_validity_rate: 1, performance_fdrc_pass_at_1: 0.5,
    raw_fdrc_pass_at_1: 0.5,
  });
  assert.strictEqual(r.model, "gemini-x");
  assert.strictEqual(r.passCell, "50.0%");
  assert.strictEqual(r.validityCell, "100.0%");
  assert.strictEqual(r.reportable, true);
});

t("leaderboardRow shows dash when not reportable", () => {
  const r = VB.leaderboardRow({
    run_id: "run_x", provider: "openai", model: "gpt",
    reportability_status: "VALIDITY_ONLY",
    fdrc_validity_rate: 0.8, performance_fdrc_pass_at_1: null,
    raw_fdrc_pass_at_1: 0.1,
  });
  assert.strictEqual(r.passCell, "—");
  assert.strictEqual(r.reportable, false);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `node src/dashboard/static/helpers.test.cjs`
Expected: FAIL with `VB.leaderboardRow is not a function`.

- [ ] **Step 3: Implement `leaderboardRow`**

In `src/dashboard/static/helpers.js`, before the `return { ... }` object, add:

```javascript
  function leaderboardRow(row) {
    const reportable = String(row.reportability_status || "").startsWith("REPORTABLE");
    return {
      run_id: row.run_id,
      provider: row.provider || "—",
      model: row.model || "—",
      yield_mode: row.yield_mode || "—",
      episodes: fmtInt(row.episode_count),
      reportable,
      reportability_status: row.reportability_status || "—",
      validityCell: fmtPct(row.fdrc_validity_rate),
      passCell: reportable ? fmtPct(row.performance_fdrc_pass_at_1) : "—",
      rawPassCell: fmtPct(row.raw_fdrc_pass_at_1),
      yieldP50: fmtMs(row.performance_yield_latency_p50_ms),
      yieldP95: fmtMs(row.performance_yield_latency_p95_ms),
      forbiddenCell: fmtPct(row.forbidden_tool_call_rate),
      cancelCell: fmtPct(row.cancel_success_rate),
      uptakeCell: fmtPct(row.correction_uptake_rate),
    };
  }
```

Then add `leaderboardRow,` to the returned object.

- [ ] **Step 4: Run test to verify it passes**

Run: `node src/dashboard/static/helpers.test.cjs`
Expected: all `ok`, exit 0.

- [ ] **Step 5: Commit**

```bash
git add src/dashboard/static/helpers.js src/dashboard/static/helpers.test.cjs
git commit -m "feat: add leaderboardRow pure helper"
```

---

## Task 7: Frontend leaderboard tab

**Files:**
- Modify: `src/dashboard/static/index.html` (tab label)
- Modify: `src/dashboard/static/app.js` (render leaderboard instead of reserved)

- [ ] **Step 1: Rename the tab**

In `src/dashboard/static/index.html`, change the second tab button text:

```html
        <button class="tab" data-tab="lab">
          <span class="tab-idx">02</span> Leaderboard
        </button>
```

- [ ] **Step 2: Render leaderboard in app.js**

In `src/dashboard/static/app.js`, replace the `renderReserved` function (the one returned for `r.tab === "lab"` at line ~697) with a leaderboard renderer:

```javascript
  async function renderReserved() {
    setStatus("leaderboard", "loading…");
    let rows;
    try {
      rows = await getJSON(`/api/leaderboard?track=${FDRC}`);
    } catch (e) {
      view.innerHTML = stateBlock({ glyph: "⚠", title: "Không tải được leaderboard", body: esc(e.message), error: true });
      return;
    }
    if (!rows.length) {
      view.innerHTML = stateBlock({ glyph: "∅", title: "Chưa có run FDRC nào", body: "Chạy run_fdrc với --agent rồi quay lại." });
      return;
    }
    const head = ["Model", "Provider", "Yield", "Episodes", "Status", "Validity", "Pass@1", "Yield p50", "Yield p95", "Forbidden", "Cancel"];
    const body = rows.map((raw) => {
      const r = H.leaderboardRow(raw);
      return `<tr class="${r.reportable ? "" : "muted"}">
        <td><b>${esc(r.model)}</b><div class="sub">${esc(r.run_id)}</div></td>
        <td>${esc(r.provider)}</td>
        <td>${esc(r.yield_mode)}</td>
        <td class="cell-num">${esc(r.episodes)}</td>
        <td>${esc(r.reportability_status)}</td>
        <td class="cell-num">${esc(r.validityCell)}</td>
        <td class="cell-num">${esc(r.passCell)}</td>
        <td class="cell-num">${esc(r.yieldP50)}</td>
        <td class="cell-num">${esc(r.yieldP95)}</td>
        <td class="cell-num">${esc(r.forbiddenCell)}</td>
        <td class="cell-num">${esc(r.cancelCell)}</td>
      </tr>`;
    }).join("");
    view.innerHTML = `<section class="panel"><h2>FDRC Leaderboard</h2>
      <table class="lb"><thead><tr>${head.map((h) => `<th>${esc(h)}</th>`).join("")}</tr></thead>
      <tbody>${body}</tbody></table></section>`;
    setStatus("leaderboard", `${rows.length} runs`);
  }
```

Note: `getJSON` is the existing fetch wrapper (line ~34); confirm the name in app.js and reuse it. If the wrapper is named differently, use that name.

- [ ] **Step 3: Manual verify in browser**

Run: `./.venv/Scripts/python.exe -m src.dashboard --port 8765`
Open `http://127.0.0.1:8765`, click tab `02 Leaderboard`. Expected: a table listing existing FDRC runs (e.g. reference runs) with one row each; non-reportable rows show `—` for Pass@1.

- [ ] **Step 4: Commit**

```bash
git add src/dashboard/static/index.html src/dashboard/static/app.js
git commit -m "feat: leaderboard tab in dashboard"
```

---

## Task 8: Live smoke run (gated on user key) + docs

**Files:**
- Modify: `docs/dashboard_usage.md` (or `docs/fdrc_benchmark_runbook.md`) — add Gemini run + leaderboard usage.

- [ ] **Step 1: Document the new commands**

Append to `docs/fdrc_benchmark_runbook.md`:

```markdown
## Chạy Gemini Live + so sánh

1. Điền `.env`: `GEMINI_API_LIVE=<key>` và `GEMINI_MODEL=<model live>`.
2. Smoke 1 domain:
   `./.venv/Scripts/python.exe run_fdrc.py --agent gemini_live --domains automotive --personas vi_north_normal --fdrc-yield-mode native_yield --output results/fdrc_smoke_gemini_native`
3. Mở dashboard `./.venv/Scripts/python.exe -m src.dashboard` → tab `02 Leaderboard` để so sánh với run OpenAI.
```

- [ ] **Step 2: Commit docs**

```bash
git add docs/fdrc_benchmark_runbook.md
git commit -m "docs: gemini live run + leaderboard usage"
```

- [ ] **Step 3: (Manual, requires user key) Live smoke**

After the user fills `.env`, run the command in Step 1 and confirm: `metrics.json` has `provider`/`model` = gemini, `fdrc_validity_rate` reported, and observed events present. This step is gated on the user's key/quota and is not blocking for the rest of the plan.

---

## Self-Review notes

- **Spec coverage:** A (Tasks 2-4), B (Task 1), C (Tasks 5-7), tests (Tasks 2-7), live smoke + docs (Task 8). All spec sections mapped.
- **Type consistency:** `to_gemini_tools`, `normalize_gemini_message(message, *, t_ms, speaking)`, `GeminiLiveViviAdapter(model, *, idle_timeout_s, session)`, `provider_for_agent`, `DashboardStore.leaderboard(track=...)`, `VB.leaderboardRow(row)` used consistently across tasks.
- **Known external uncertainty:** exact google-genai Live API surface (`send_realtime_input`, `send_tool_response`, `receive`, `connect`) may differ by version. All SDK calls are isolated in the adapter; the pure functions (`to_gemini_tools`, `normalize_gemini_message`) and the injected-`session` test path verify behavior offline. If the installed SDK differs, adjust only the SDK-call lines in `start_session`/`send_*`/`_reader_loop`, guided by the offline tests.
```
