# Hướng Dẫn Chạy Dự Án Vivi Voice Bench

## Context

Tài liệu này dùng để bàn giao repository `voice-bench` cho người mới nhận dự án, với mục tiêu giúp họ dựng môi trường, chạy benchmark tối thiểu, đọc kết quả, và mở dashboard local mà không cần hiểu toàn bộ thiết kế evaluator ngay từ đầu.

Repository hiện có hai benchmark chính:

| Benchmark | Entry point | Mục đích vận hành |
|---|---|---|
| Policy-Grounded Voice Command Gating | `run_policy_gating.py` | Đánh giá quyết định `execute`, `clarify`, `refuse`, hoặc `defer` theo policy và trạng thái xe. |
| Full-Duplex Repair-to-Commit | `run_fdrc.py` | Đánh giá khả năng nhường lời khi user chen ngang, tiếp nhận sửa hoặc hủy ý định, và chỉ commit ý định cuối cùng. |
| Dashboard local | `python -m src.dashboard` | Đọc `results/<run_name>/episodes.jsonl` và `metrics.json`, hiển thị KPI, failure taxonomy, episode explorer, và leaderboard. |

Luồng vận hành chuẩn là:

```text
setup environment -> configure .env -> run reference smoke -> run provider/imported logs -> open dashboard -> inspect metrics and failures
```

## Problem Statement

Người chạy dự án cần phân biệt ba loại run vì chúng có ý nghĩa sản phẩm khác nhau:

| Loại run | Cách tạo | Có được báo cáo như performance thật không? | Mục đích đúng |
|---|---|---:|---|
| Reference-agent | `--reference-agent` | Không | Kiểm tra evaluator, schema, asset, dashboard, và plumbing nội bộ. |
| Provider surrogate | `--agent openai_realtime`, `--agent openai_text`, hoặc `--agent gemini_live` | Có, nếu evidence hợp lệ | Đánh giá model/provider thật qua adapter surrogate. |
| Imported Vivi logs | `--episode-logs path\to\episodes.jsonl` | Có, nếu log đúng contract | Chấm log xuất ra từ hệ thống Vivi thật hoặc pipeline bên ngoài. |

Điểm quan trọng là `reference-agent` thường có kết quả rất cao vì nó là oracle synthetic; kết quả này chỉ dùng để xác nhận bộ chấm hoạt động đúng, không đại diện cho năng lực Vivi hoặc model provider.

## Technical Deep-Dive

### 1. Yêu Cầu Môi Trường

| Thành phần | Khuyến nghị | Ghi chú |
|---|---|---|
| Python | `>=3.10` | `pyproject.toml` khai báo `requires-python = ">=3.10"`. |
| Hệ điều hành | Windows PowerShell hoặc môi trường shell tương đương | Các lệnh bên dưới viết theo PowerShell vì repo đang được phát triển trên Windows. |
| Package manager | Conda, `.venv`, hoặc `pip` | Repo có `pyproject.toml`; môi trường nội bộ hiện thường chạy bằng Conda `base` hoặc `.venv`. |
| API keys | Chỉ cần khi chạy provider | Reference-agent và evaluate existing logs không cần gọi provider. |

Từ thư mục gốc repository:

```powershell
cd C:\Users\Admin\Desktop\voice-bench
```

Kiểm tra Python:

```powershell
python --version
python -c "import sys; print(sys.executable)"
```

Nếu dùng Conda:

```powershell
conda run -n base python -c "import sys; print(sys.executable)"
```

### 2. Cài Đặt Dependency

Nếu repository đã có `.venv` hoặc môi trường Conda được chuẩn bị sẵn, có thể bỏ qua bước tạo môi trường và chỉ kiểm tra import bằng phần verification ở cuối tài liệu.

Nếu cần dựng mới bằng virtual environment:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .
```

Nếu PowerShell chặn activate script, chạy trực tiếp Python trong `.venv`:

```powershell
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e .
```

Nếu dùng Conda `base`:

```powershell
conda run -n base python -m pip install -e .
```

### 3. Cấu Hình `.env`

Tạo file `.env` ở root repository khi cần chạy provider. Runner sẽ tự load file này qua `src/env.py`.

```text
OPENAI_API_KEY=...
ELEVENLABS_API_KEY=...
TAU2_VOICE_ID_MIEN_BAC=...
TAU2_VOICE_ID_MIEN_TRUNG=...
TAU2_VOICE_ID_MIEN_NAM=...
GEMINI_API_LIVE=...
GEMINI_MODEL=...
```

| Biến môi trường | Khi nào cần | Ý nghĩa |
|---|---|---|
| `OPENAI_API_KEY` | Chạy `openai_text` hoặc `openai_realtime` | Key cho OpenAI adapter. |
| `ELEVENLABS_API_KEY` | Khi pipeline cần sinh TTS/audio asset | Key tạo giọng nói nếu chưa có cache/audio. |
| `TAU2_VOICE_ID_MIEN_BAC`, `TAU2_VOICE_ID_MIEN_TRUNG`, `TAU2_VOICE_ID_MIEN_NAM` | Khi sinh speech asset theo vùng miền | Voice ID cho persona Bắc, Trung, Nam. |
| `GEMINI_API_LIVE` hoặc `GEMINI_API_KEY` | Chạy `gemini_live` | `src/env.py` tự alias sang `GOOGLE_API_KEY`. |
| `GEMINI_MODEL` | Chạy `gemini_live` mà không truyền `--model` | Model mặc định cho Gemini Live. |

Không commit `.env` hoặc API key vào repository.

### 4. Chạy Reference Smoke Không Tốn API

Reference smoke là bước đầu tiên nên chạy sau khi cài dependency vì nó kiểm tra asset, schema, evaluator, runner, và ghi output vào `results/`.

Nếu dùng Python hiện tại:

```powershell
python run_policy_gating.py --reference-agent --output results\policy_gating_reference
python run_fdrc.py --reference-agent --output results\fdrc_reference
```

Nếu dùng `.venv`:

```powershell
.\.venv\Scripts\python.exe run_policy_gating.py --reference-agent --output results\policy_gating_reference
.\.venv\Scripts\python.exe run_fdrc.py --reference-agent --output results\fdrc_reference
```

Nếu dùng Conda:

```powershell
conda run -n base python run_policy_gating.py --reference-agent --output results\policy_gating_reference
conda run -n base python run_fdrc.py --reference-agent --output results\fdrc_reference
```

Mỗi run hợp lệ tạo ra:

```text
results/<run_name>/episodes.jsonl
results/<run_name>/metrics.json
```

### 5. Chạy Policy-Gating Provider Smoke

Chạy smoke nhỏ trước khi chạy full matrix để giới hạn chi phí và phát hiện lỗi key, quota, adapter hoặc schema.

OpenAI text surrogate:

```powershell
python run_policy_gating.py --domains automotive --agent openai_text --model gpt-4o-mini --personas vi_north_normal --output results\policy_gating_openai_text_smoke
```

OpenAI realtime surrogate:

```powershell
python run_policy_gating.py --domains automotive --agent openai_realtime --model gpt-realtime-mini --personas vi_north_normal --output results\policy_gating_openai_realtime_smoke
```

Gemini Live surrogate:

```powershell
python run_policy_gating.py --domains automotive --agent gemini_live --personas vi_north_normal --output results\policy_gating_gemini_smoke
```

### 6. Chạy FDRC Provider Smoke

FDRC yêu cầu evidence timeline nghiêm ngặt hơn policy-gating, vì vậy nên chạy từng domain nhỏ trước.

OpenAI realtime, một domain:

```powershell
python run_fdrc.py --agent openai_realtime --model gpt-realtime-mini --domains automotive --personas vi_north_normal --fdrc-yield-mode native_yield --output results\fdrc_openai_smoke_automotive
```

Gemini Live, một domain:

```powershell
python run_fdrc.py --agent gemini_live --domains automotive --personas vi_north_normal --fdrc-yield-mode native_yield --output results\fdrc_gemini_smoke_automotive
```

Full matrix chỉ nên chạy sau khi smoke pass ở mức validity chấp nhận được:

```powershell
python run_fdrc.py --agent openai_realtime --model gpt-realtime-mini --domains automotive,navigation,media_phone --personas vi_north_slow,vi_north_normal,vi_north_fast,vi_central_slow,vi_central_normal,vi_central_fast,vi_south_slow,vi_south_normal,vi_south_fast --fdrc-yield-mode native_yield --output results\fdrc_openai_full
```

### 7. Evaluate Existing Vivi Logs

Nếu đã có episode logs từ hệ thống khác, dùng `--episode-logs` để chấm offline. Đường này không gọi model provider.

```powershell
python run_policy_gating.py --episode-logs path\to\policy_episodes.jsonl --output results\policy_gating_imported
python run_fdrc.py --episode-logs path\to\fdrc_episodes.jsonl --output results\fdrc_imported
```

Episode log phải tuân thủ contract trong `src/schema.py`; runner sẽ chuyển malformed episode thành validation failure có cấu trúc thay vì coi là pass.

### 8. Mở Dashboard

Dashboard đọc trực tiếp thư mục `results/`.

```powershell
python -m src.dashboard --host 127.0.0.1 --port 8765
```

Nếu dùng `.venv`:

```powershell
.\.venv\Scripts\python.exe -m src.dashboard --host 127.0.0.1 --port 8765
```

Mở trình duyệt:

```text
http://127.0.0.1:8765
```

Nếu muốn dashboard đọc thư mục kết quả khác:

```powershell
python -m src.dashboard --host 127.0.0.1 --port 8765 --results-dir path\to\results
```

Dashboard sẽ cảnh báo khi `metrics.json` không khớp `episode_set_hash`; trong trường hợp đó, dashboard có thể derive metrics lại từ `episodes.jsonl`.

### 9. Kiểm Tra Chất Lượng Cục Bộ

Chạy compile check:

```powershell
python -m py_compile run_policy_gating.py run_fdrc.py
```

Chạy lint:

```powershell
python -m ruff check src run_policy_gating.py run_fdrc.py
```

Chạy test nhanh cho các thành phần chính:

```powershell
python -m pytest -q tests\test_vivi_voice_benchmark.py tests\test_policy_gating_evaluator.py tests\test_policy_gating_dataset.py tests\test_fdrc_validity.py tests\test_dashboard.py
```

Chạy toàn bộ test suite:

```powershell
python -m pytest -q
```

### 10. Sinh Hoặc Làm Mới Audio Assets

Chỉ chạy bước này khi thiếu audio/noise segments hoặc sau khi sửa source catalog.

Segment cabin noise:

```powershell
python -u scripts\segment_cabin_noise.py
```

Rebuild sạch cabin noise segments:

```powershell
python -u scripts\segment_cabin_noise.py --force
```

Regenerate speech benchmark assets:

```powershell
python scripts\generate_vivi_speech_assets.py
```

Các lệnh này có thể tốn thời gian và có thể phụ thuộc API key/audio cache.

### 11. Cấu Trúc Thư Mục Quan Trọng

| Path | Vai trò |
|---|---|
| `run_policy_gating.py` | CLI wrapper cho policy-gating benchmark. |
| `run_fdrc.py` | CLI chính cho Full-Duplex Repair-to-Commit benchmark. |
| `data/jsonl/` | Thư mục tập trung cho các dataset JSONL đầu vào của benchmark. |
| `src/runner.py` | Logic chung: chọn overlays, build/load episodes, evaluate, merge, save results. |
| `src/evaluator/` | Deterministic evaluators và metric summarizers. |
| `src/orchestrator/` | Adapter orchestration cho provider/model surrogate. |
| `src/tools/` | Vivi tool schema, registry, mock tool server. |
| `src/dashboard/` | FastAPI backend và static dashboard. |
| `data/jsonl/speech_task_overlays.jsonl` | Overlay mặc định cho policy-gating và một phần benchmark speech. |
| `data/jsonl/fdrc_golden_enriched_v2_90.jsonl` | Overlay mặc định hiện tại cho FDRC. |
| `data/domains/` | Domain tasks, policy, database fixtures. |
| `results/` | Output benchmark run local. |
| `archive_runs/` | Run đã lưu để tham chiếu hoặc demo. |
| `docs/` | Tài liệu benchmark, dashboard, runbook, và hướng dẫn vận hành. |

### 12. Troubleshooting

| Triệu chứng | Nguyên nhân thường gặp | Cách xử lý |
|---|---|---|
| `ModuleNotFoundError` | Chưa cài package hoặc đang dùng sai Python interpreter | Kiểm tra `python -c "import sys; print(sys.executable)"`, sau đó chạy `python -m pip install -e .`. |
| Provider run báo thiếu key | `.env` chưa có key hoặc shell không thấy biến môi trường | Thêm key vào `.env`, hoặc export trực tiếp trong shell, rồi chạy lại. |
| Gemini Live không nhận key | Chưa có `GEMINI_API_LIVE`, `GEMINI_API_KEY`, hoặc `GOOGLE_API_KEY` | Điền một trong các biến Gemini; `src/env.py` sẽ alias Gemini key sang `GOOGLE_API_KEY`. |
| Dashboard không thấy run mới | Output không nằm dưới `results/` hoặc dashboard đang đọc `--results-dir` khác | Chạy dashboard với đúng `--results-dir`, hoặc ghi output vào `results\<run_name>`. |
| Metrics bị cảnh báo hash mismatch | `episodes.jsonl` thay đổi sau khi tạo `metrics.json` | Chạy lại runner/evaluator hoặc để dashboard derive từ episode logs khi phân tích forensic. |
| FDRC pass thấp nhưng validity cũng thấp | Thiếu evidence full-duplex như yield, interrupt, hoặc tool timestamp | Kiểm tra `voice_events`, `latency`, `tool_calls[*].t_ms`, và đọc failure taxonomy trong dashboard. |
| Provider run tốn chi phí hoặc chậm | Full matrix nhân theo domain, overlay, persona, audio condition | Luôn chạy smoke nhỏ với một domain và một persona trước khi full matrix. |

## Strategic Recommendations

| Ưu tiên | Khuyến nghị | Lý do kỹ thuật và sản phẩm |
|---|---|---|
| Reliability | Luôn chạy `--reference-agent` trước provider run | Bước này tách lỗi evaluator/schema/asset khỏi lỗi model provider, giảm thời gian debug và tránh chi phí không cần thiết. |
| Scalability | Chạy smoke theo từng domain trước full matrix | Benchmark có tổ hợp overlay x persona x provider; chia nhỏ giúp kiểm soát quota, retry, và failure localization. |
| Latency | Với FDRC, không trộn `native_yield` và `client_cancel_yield` trong cùng một kết luận | Hai mode đo hai tầng sản phẩm khác nhau: năng lực model/provider và năng lực cancellation của product stack. |
| Cost-to-serve | Ưu tiên evaluate existing Vivi logs offline khi có log thật | Offline evaluation không tốn provider cost và phản ánh hành vi hệ thống đích tốt hơn surrogate model. |
| Reporting validity | Chỉ báo cáo provider/imported run có provenance rõ và evidence hợp lệ | Reference/sample/internal run là diagnostic artifact; đưa chúng vào báo cáo performance sẽ tạo kết luận sai lệch. |

Quy trình tối thiểu khuyến nghị cho người mới nhận repo:

```powershell
python -m pip install -e .
python run_policy_gating.py --reference-agent --output results\policy_gating_reference
python run_fdrc.py --reference-agent --output results\fdrc_reference
python -m src.dashboard --host 127.0.0.1 --port 8765
```
