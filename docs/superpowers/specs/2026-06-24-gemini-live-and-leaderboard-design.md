# Spec: Gemini Live adapter + Dashboard leaderboard so sánh model (FDRC)

- Ngày: 2026-06-24
- Track liên quan: `full_duplex_repair_to_commit` (FDRC)
- Trạng thái: Draft chờ review

## 1. Mục tiêu

Cho phép chạy benchmark FDRC với **nhiều provider/model realtime** (hiện có OpenAI Realtime, thêm **Gemini Live**) bằng key trong `.env`, rồi **so sánh kết quả trên dashboard bằng một bảng leaderboard**.

Phạm vi gói gọn trong 3 phần A/B/C dưới đây. Không restructure module, không đổi schema overlay, không thêm DB/API phức tạp.

## 2. Bối cảnh code hiện tại (đã xác minh)

- Adapter interface: `ViviAgentAdapter` ([src/adapters/base_vivi_agent_adapter.py](../../../src/adapters/base_vivi_agent_adapter.py)) có 8 method: `start_session`, `send_text`, `send_audio_chunk`, `receive_events`, `send_tool_result`, `commit_audio_turn`, `cancel_response`, `close`.
- Orchestrator điều khiển realtime trong `_run_audio_episode` ([src/orchestrator/full_duplex_orchestrator.py](../../../src/orchestrator/full_duplex_orchestrator.py)): stream PCM16 100ms qua `send_audio_chunk`, `commit_audio_turn`, `cancel_response`, và drain `receive_events` song song. Tool-call xử lý generic trong `_drain_adapter_events` — **adapter đúng interface là cắm vào FDRC chạy được, không cần sửa orchestrator/evaluator.**
- `env.py` đã alias sẵn `GEMINI_API_LIVE`/`GEMINI_API_KEY` → `GOOGLE_API_KEY`.
- `.env` đã có `GEMINI_API_LIVE`, `GEMINI_MODEL` (giá trị đang trống).
- `google-genai` **chưa cài**; `websockets 16.0` có sẵn.
- `audio_io.TARGET_SR = 24000` + có `resample()`, `pcm16_to_float()`, `float_to_pcm16()`.
- Hardcode `provider="openai"` ở [orchestrator:98](../../../src/orchestrator/full_duplex_orchestrator.py#L98) và [run_fdrc:113](../../../src/run_fdrc.py#L113).
- Evaluator/summarize đã có đầy đủ: validity, raw/performance pass@1, reportability, failure taxonomy. Leaderboard **chỉ đọc lại**, không tính lại.
- `list_runs()` ([service.py:988](../../../src/dashboard/service.py#L988)) đã trả per-run metadata; chưa có endpoint leaderboard.

## 3. Phần A — Gemini Live adapter

### A.1 File mới: `src/adapters/gemini_live_vivi_adapter.py`

Lớp `GeminiLiveViviAdapter(ViviAgentAdapter)` dùng SDK `google-genai`:

```python
from google import genai
client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])
session = await client.aio.live.connect(model=self.model, config=config).__aenter__()
```

`config` (LiveConnectConfig):
- `system_instruction` = system_prompt
- `tools` = function declarations chuyển từ tool schema của ta (reuse `get_openai_tool_schemas`/`vivi_tool_schema`; map sang `{"function_declarations":[{name, description, parameters}]}`)
- `response_modalities = ["AUDIO"]`
- `input_audio_transcription = {}` và `output_audio_transcription = {}` (bật transcript hai chiều)
- turn-taking: dùng **VAD tự động** mặc định (đơn giản, đủ cho FDRC). Nếu cần can thiệp, dùng activity signals ở `commit_audio_turn`/`cancel_response`.

### A.2 Mapping event Gemini → NormalizedEvent (giữ nguyên type sẵn có)

| Tín hiệu Gemini | NormalizedEvent type |
|---|---|
| audio data chunk đầu tiên của turn | `assistant_speech_start` (một lần) |
| mỗi `server_content` audio chunk | `assistant_audio_delta` |
| `server_content.output_transcription.text` | `assistant_transcript_delta` (+ `text`) |
| `server_content.input_transcription.text` | `user_transcript_done` (+ `text`) |
| `tool_call.function_calls[]` | `tool_call` (+ `tool`, `args`, `call_id`) |
| `server_content.interrupted == true` | `assistant_yielded` |
| `server_content.turn_complete`/`generation_complete` | `assistant_speech_stop` |
| exception / error | `session_error` (+ `error`) |

Dùng đồng hồ `time.perf_counter()` từ `start_session` để gắn `t_ms` (giống adapter OpenAI). Reader loop nền đẩy event vào `asyncio.Queue`, `receive_events()` có idle-timeout để không treo (giống OpenAI adapter).

### A.3 Audio & turn control

- `send_audio_chunk(pcm24k_bytes, t_ms)`: resample 24k→16k (`pcm16_to_float` → `resample(.., 24000, 16000)` → `float_to_pcm16`) rồi gửi `session.send_realtime_input(audio=...)` ở 16kHz/PCM16.
- `commit_audio_turn()`: với VAD tự động là no-op hoặc gửi `activity_end` nếu dùng manual VAD.
- `cancel_response()`: Gemini tự ngắt khi có input mới; với `client_cancel_yield` gửi tín hiệu activity/interrupt phù hợp. Nếu SDK không hỗ trợ cancel tường minh thì để no-op an toàn và ghi rõ trong code.
- `send_tool_result(call_id, result)`: gửi `session.send_tool_response(function_responses=[{id/name, response}])`.
- `close()`: đóng session + dừng reader task + đẩy sentinel `None`.

### A.4 Wiring

- `build_adapter`: thêm nhánh `agent == "gemini_live"` → `GeminiLiveViviAdapter(model=model)`.
- `AgentName = Literal["openai_text", "openai_realtime", "gemini_live"]`.
- `run_fdrc.py --agent choices = ["openai_realtime", "gemini_live"]`; default model cho gemini lấy từ `GEMINI_MODEL` nếu có.
- Trong `_run_audio_episode`, nhánh `if agent == "openai_realtime"` đổi thành "agent là realtime audio" (gồm cả gemini_live) để chạy đường audio. (run_fdrc:75 cũng vậy.)
- Dependency: thêm `google-genai` vào `pyproject.toml` và cài vào `.venv`.

## 4. Phần B — Tổng quát hóa provider/model

- Thêm map `AGENT_TO_PROVIDER = {"openai_realtime": "openai", "openai_text": "openai", "gemini_live": "google"}`.
- orchestrator episode dict: `"provider"` lấy từ map theo agent thay vì hardcode `"openai"`.
- `run_fdrc.py`: `provider=`, `adapter=` annotate theo agent; `model` truyền đúng cho từng provider.
- Kết quả: mỗi episode/run mang đúng `provider` + `model` để leaderboard nhóm.

## 5. Phần C — Dashboard leaderboard

### C.1 Backend

- `DashboardStore.leaderboard(track="full_duplex_repair_to_commit")`: duyệt các run FDRC, mỗi run trả 1 dòng đọc từ `run_summary`/`metrics`:
  - `run_id`, `provider`, `model`, `yield_mode` (từ run_metadata `fdrc_yield_modes`), `run_kind`, `data_provenance`, `episode_count`, `updated_at`
  - `reportability_status`, `fdrc_validity_rate`
  - `raw_fdrc_pass_at_1`, `performance_fdrc_pass_at_1`
  - `performance_yield_latency_p50_ms`, `performance_yield_latency_p95_ms`, `performance_yield_latency_pass_rate`
  - `forbidden_tool_call_rate`, `cancel_success_rate`, `correction_uptake_rate`, `old_intent_suppression_rate`
- Route: `GET /api/leaderboard?track=...` trong [app.py](../../../src/dashboard/app.py).
- Loại run reference khỏi so sánh hiệu năng theo mặc định (chỉ provider), nhưng vẫn liệt kê có gắn nhãn provenance để tránh nhầm plumbing là performance.

### C.2 Frontend

- Đổi tab `02 Reserved` → `02 Leaderboard` ([index.html](../../../src/dashboard/static/index.html)).
- Bảng sort được (click cột để sort), mỗi dòng 1 model/run; tô màu nhẹ theo `reportability_status`; cột pass@1 hiển thị `performance` khi reportable, ngược lại hiện `—` + tooltip lý do (validity thấp).
- Render thuần từ `/api/leaderboard`; logic format thuần đặt trong `helpers.js` để test bằng `helpers.test.cjs` (đã có hạ tầng test này).

## 6. Chiến lược test

- **Offline (không cần key):**
  - Unit test cho `_normalize`/mapping của Gemini adapter: feed payload Gemini giả lập → assert ra đúng NormalizedEvent type/text/args. (Tách hàm normalize thuần để test không cần network.)
  - Unit test `leaderboard()` với 2 run giả (1 openai, 1 gemini) trong thư mục results tạm → assert đúng số dòng, đúng provider/model, đúng metric chiếu lại.
  - Test format leaderboard trong `helpers.test.cjs`.
- **Live smoke (cần key của bạn):** điền `GEMINI_API_LIVE`+`GEMINI_MODEL`, chạy `run_fdrc --agent gemini_live --domains automotive --personas vi_north_normal` 1 domain để kiểm validity > 0 và event observed đầy đủ. Phần này chạy sau khi bạn cấp key.

## 7. Tiêu chí hoàn thành

1. `run_fdrc --agent gemini_live` chạy được đường audio FDRC mà không sửa orchestrator/evaluator core.
2. Episode/run Gemini mang đúng `provider="google"` + `model`.
3. Reference FDRC vẫn 90/90 pass (không hồi quy).
4. `/api/leaderboard` trả bảng nhiều model; tab Leaderboard hiển thị so sánh, tách reference/provider rõ ràng.
5. Unit test offline cho adapter-normalize + leaderboard + helpers pass.

## 8. Non-goals

- Không restructure module theo §4.1 của `full_duplex_backend_plan.md`.
- Không đổi schema overlay (`speech_overlay_id`/`benchmark_track` giữ nguyên).
- Không thêm DB/Postgres/SQLite.
- Không làm view so sánh A/B chi tiết (chỉ leaderboard, theo lựa chọn của bạn).
- Không tự ý điền/khởi tạo key Gemini.

## 9. Rủi ro / phụ thuộc

- Cần cài `google-genai`; API surface của Live API có thể khác nhẹ giữa version → cô lập mọi call SDK trong adapter, tách hàm normalize thuần để test.
- Live smoke phụ thuộc key `GEMINI_API_LIVE` + quota của bạn.
- Sample-rate mismatch (24k↔16k) xử lý trong adapter; nếu Gemini yêu cầu format khác sẽ điều chỉnh tại chỗ.
