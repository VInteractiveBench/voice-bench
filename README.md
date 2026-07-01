# Vivi Voice CarBench VN

## Context

`Vivi Voice CarBench VN` là benchmark tương tác giọng nói tiếng Việt trong bối cảnh ô tô. Dự án không chấm ASR thuần túy hay độ tự nhiên hội thoại; evaluator tập trung vào quyết định policy, tool trajectory, tool arguments, final state, critical slots, evidence full-duplex, và failure taxonomy.

| Track | Entry point | Câu hỏi chính |
|---|---|---|
| Policy-Grounded Voice Command Gating | `run_policy_gating.py` | Vivi có chọn đúng `execute`, `clarify`, `refuse`, hoặc `defer` theo policy và trạng thái xe không? |
| Full-Duplex Repair-to-Commit | `run_fdrc.py` | Khi user chen ngang, sửa lệnh, hoặc hủy lệnh, Vivi có yield đúng lúc và chỉ commit intent cuối cùng không? |

Surface chính hiện nằm trong `src/`, với hai CLI ở root repo. Reference-agent là oracle synthetic để kiểm tra evaluator và dashboard plumbing; không được báo cáo như hiệu năng Vivi hoặc provider thật.

## Problem Statement

Text benchmark thường bỏ sót hai rủi ro sản phẩm quan trọng: năng lực task-grounded suy giảm khi chuyển sang voice, và side effect sai khi người dùng ngắt lời hoặc sửa intent đang xử lý. Repo này tách tầng tạo episode khỏi tầng evaluation tất định, nhờ đó log từ Vivi production, provider surrogate, hoặc reference-agent đều có thể được chấm qua cùng contract JSONL.

## Quick Start

```powershell
cd C:\Users\Admin\Desktop\voice-bench
python -m pip install -e .

python run_policy_gating.py --reference-agent --output results\policy_gating_reference
python run_fdrc.py --reference-agent --output results\fdrc_reference

python -m src.dashboard --host 127.0.0.1 --port 8765
```

Mở dashboard:

```text
http://127.0.0.1:8765
```

Mỗi run hợp lệ ghi:

```text
results/<run_name>/episodes.jsonl
results/<run_name>/metrics.json
```

## Technical Deep-Dive

### Cấu Trúc Chính

| Path | Vai trò |
|---|---|
| `run_policy_gating.py` | CLI cho benchmark policy-gating. |
| `run_fdrc.py` | CLI cho Full-Duplex Repair-to-Commit và lệnh inspect FDRC run. |
| `src/runner.py` | Pipeline chung: load, build, evaluate, merge, save. |
| `src/evaluator/` | Evaluator tất định, metric summarizer, contract, failure taxonomy. |
| `src/orchestrator/` | Orchestration cho provider/model surrogate và policy outcome. |
| `src/adapters/` | Adapter OpenAI và Gemini. |
| `src/tools/` | Vivi tool registry, schema validation, mock tool server. |
| `src/dashboard/` | FastAPI dashboard và static UI. |
| `data/jsonl/` | Overlay datasets chuẩn của benchmark. |
| `docs/` | Runbook, benchmark definition, dashboard guide, product notes. |

### Datasets Chuẩn

| Dataset | Namespace | Vai trò hiện tại |
|---|---|---|
| `data/jsonl/speech_task_overlays.jsonl` | `pg_*`, legacy `fdrc_vehicle_*` | Default của policy-gating; giữ legacy MVP FDRC overlays cho test và reference. |
| `data/jsonl/fdrc_golden_enriched_v2_90.jsonl` | `fdrc_v2_*` | Default và canonical golden set của FDRC. |
| `data/jsonl/fdrc_golden_dataset.jsonl` | `fdrc_balanced_v1`, `fdrc_*` | Dataset FDRC trung gian, giữ cho generator và regression tests. |

`run_fdrc.py` chỉ kiểm tra count MVP khi `--overlays` trỏ tới `speech_task_overlays.jsonl`; với FDRC v2_90, preflight kiểm tra shape và contract thay vì ép count legacy.

### Loại Run

| Loại run | Command pattern | Báo cáo performance? | Mục đích |
|---|---|---:|---|
| Reference-agent | `--reference-agent` | Không | Kiểm tra evaluator, assets, schema, dashboard, metric plumbing mà không tốn API. |
| Imported logs | `--episode-logs path\to\episodes.jsonl` | Có, nếu provenance và evidence hợp lệ | Chấm offline log từ Vivi production hoặc pipeline ngoài. |
| Provider surrogate | `--agent openai_text`, `--agent openai_realtime`, `--agent gemini_live` | Có, nếu validity đủ | Đo hành vi provider/model qua cùng tool và evaluator contract. |

### Chấm Existing Logs

```powershell
python run_policy_gating.py --episode-logs path\to\policy_episodes.jsonl --output results\policy_gating_imported
python run_fdrc.py --episode-logs path\to\fdrc_episodes.jsonl --output results\fdrc_imported
```

Episode malformed được chuyển thành validation failure có cấu trúc, không được xem là pass.

### Provider Smoke Runs

Điền `.env` khi cần chạy provider:

```text
OPENAI_API_KEY=...
GEMINI_API_LIVE=...
GEMINI_MODEL=...
ELEVENLABS_API_KEY=...
```

Policy-gating smoke:

```powershell
python run_policy_gating.py --domains automotive --agent openai_text --model gpt-4o-mini --personas vi_north_normal --output results\policy_gating_openai_text_smoke
python run_policy_gating.py --domains automotive --agent openai_realtime --model gpt-realtime-mini --personas vi_north_normal --output results\policy_gating_openai_realtime_smoke
python run_policy_gating.py --domains automotive --agent gemini_live --personas vi_north_normal --output results\policy_gating_gemini_smoke
```

FDRC smoke:

```powershell
python run_fdrc.py --domains automotive --agent openai_realtime --model gpt-realtime-mini --personas vi_north_normal --fdrc-yield-mode native_yield --output results\fdrc_openai_smoke
python run_fdrc.py --domains automotive --agent gemini_live --personas vi_north_normal --fdrc-yield-mode native_yield --output results\fdrc_gemini_smoke
```

FDRC hỗ trợ `--audio-condition`, `--audio-conditions`, `--persona-from-overlay`, và `--user-simulator off|live|replay`. Không gộp `native_yield` và `client_cancel_yield` thành một số vì hai mode đo hai tầng sản phẩm khác nhau.

### Dashboard

```powershell
python -m src.dashboard --host 127.0.0.1 --port 8765 --results-dir results
```

Dashboard đọc `episodes.jsonl` và `metrics.json`, kiểm tra `episode_set_hash`, và tự derive metrics từ episodes khi metrics đã stale. UI tách benchmark/provider runs khỏi reference, sample, và internal diagnostic runs.

### Verification

```powershell
python -m py_compile run_policy_gating.py run_fdrc.py
python -m ruff check src run_policy_gating.py run_fdrc.py
python -m pytest -q tests\test_vivi_voice_benchmark.py tests\test_policy_gating_evaluator.py tests\test_policy_gating_dataset.py tests\test_fdrc_validity.py tests\test_dashboard.py
```

### Asset Maintenance

```powershell
python -u scripts\segment_cabin_noise.py
python -u scripts\segment_cabin_noise.py --force
python scripts\generate_vivi_speech_assets.py
```

Chỉ regenerate audio và benchmark assets khi sửa source catalog, thiếu audio cache, hoặc thay đổi cabin-noise segmentation inputs.

## Strategic Recommendations

| Ưu tiên | Khuyến nghị | Lý do |
|---|---|---|
| Reliability | Chạy reference-agent trước provider run. | Tách lỗi evaluator/schema/asset/dashboard khỏi lỗi provider hoặc model. |
| Scalability | Smoke một domain và một persona trước full matrix. | Provider run nhân theo overlay, persona, audio condition, model; smoke nhỏ giảm rủi ro quota và tăng khả năng định vị lỗi. |
| Latency | Giữ FDRC `--tick-ms 200` và ghi rõ yield mode. | Tick cố định giữ tính so sánh; yield mode thay đổi tầng latency được đo. |
| Reporting validity | Chỉ báo cáo provider hoặc imported run có provenance rõ và evidence validity đủ. | Reference, sample, internal runs là artifact chẩn đoán, không phải performance sản phẩm. |
| Cost-to-serve | Ưu tiên chấm offline Vivi production logs khi có log thật. | Offline evaluation không tốn provider cost và phản ánh hệ thống đích tốt hơn surrogate adapter. |

## Further Reading

| Document | Nội dung |
|---|---|
| `docs/huong_dan_chay_du_an.md` | Hướng dẫn setup và vận hành chi tiết. |
| `docs/fdrc_benchmark_runbook.md` | FDRC tiers, commands, metric interpretation. |
| `docs/benchmark_1_full_duplex_repair_to_commit.md` | Định nghĩa benchmark FDRC. |
| `docs/benchmark_2_policy_grounded_voice_command_gating.md` | Định nghĩa benchmark policy-gating. |
| `docs/dashboard_usage.md` | Dashboard usage, metric drilldown, data integrity. |
| `docs/flow.md` | Luồng benchmark và evaluation end-to-end. |
