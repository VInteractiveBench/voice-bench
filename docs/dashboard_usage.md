# Hướng Dẫn Sử Dụng Dashboard Vivi Voice Bench

## Context

Dashboard `Vivi Voice Bench` là công cụ local để đọc kết quả trong `results/` và quan sát hai benchmark chính:

| Benchmark | Mục đích |
|---|---|
| `Text-to-Voice Capability Retention` | Đo mức giữ năng lực từ text baseline sang voice, bao gồm tool calls, arguments, final state và critical slots. |
| `Full-Duplex Repair-to-Commit` | Đo khả năng nhường lời khi user chen ngang, tiếp nhận sửa/hủy, chặn ý định cũ và chỉ commit ý định cuối cùng. |

Dashboard đọc:

```text
results/<run_name>/episodes.jsonl
results/<run_name>/metrics.json
```

Nếu `metrics.json` không khớp `episode_set_hash`, dashboard tự derive metrics từ `episodes.jsonl` và hiển thị `metric_source=episodes.jsonl`.

## Cách Chạy

```powershell
cd C:\Users\Admin\Desktop\voice-bench
.\.venv\Scripts\python.exe -m src.dashboard --host 127.0.0.1 --port 8765
```

Mở:

```text
http://127.0.0.1:8765
```

## Full Metrics

Dashboard có hai tầng hiển thị:

| Khu vực | Ý nghĩa |
|---|---|
| KPI chính/phụ | Các chỉ số quan trọng nhất theo benchmark đang chọn. |
| Toàn bộ metrics | Metric catalog đầy đủ từ evaluator, runner và dashboard derivation. |

Metric catalog chuẩn hóa mỗi metric thành:

```json
{
  "key": "voice_capability_retention",
  "label": "Giữ năng lực voice cabin",
  "value": 0.83,
  "unit": "rate",
  "group": "retention",
  "source": "metrics.json",
  "denominator": 30,
  "nullable": false,
  "null_reason": null,
  "status": "ok"
}
```

Các nhóm metric gồm `Overview`, `Tool / State`, `Policy`, `Text-to-Voice Retention`, `Retention Degradation`, `Full-Duplex Repair-to-Commit`, `Latency`, và `Contract / Data Quality`.

## Drilldown

Click một metric trong catalog hoặc KPI card sẽ áp dụng filter episode nếu metric có mapping rõ ràng:

| Metric | Drilldown |
|---|---|
| `policy_violation_rate` | Episode có `POLICY_VIOLATION`. |
| `tool_validation_error_rate` | Episode có validation errors. |
| `critical_slot_accuracy` | Episode sai critical slot. |
| `yield_latency_*` | Episode có yield latency cao. |
| `forbidden_tool_call_rate` | Episode có `FORBIDDEN_TOOL_CALL`. |
| `correction_uptake_rate` | Episode có `CORRECTION_NOT_UPTAKEN`. |
| `cancel_success_rate` | Episode có `CANCEL_NOT_RESPECTED`. |

Metric không có mapping trực tiếp sẽ hiển thị thông báo và không thay đổi bảng episode.

### Giải thích cách tính metric (audit & trace)

Bấm vào bất kỳ thẻ metric/KPI nào ở tab Full-Duplex sẽ mở hộp thoại giải thích, gọi `GET /api/runs/{run_id}/metrics/{key}/explain`. Hộp thoại hiển thị:

- **Công thức** (tiếng Việt) của metric.
- **Giá trị hiển thị = tử số / mẫu số**: tử số/mẫu số được tính lại trực tiếp từ `episodes.jsonl` bằng đúng predicate của bộ chấm (`fdrc_contract`/`fdrc_validity`), kèm nhãn mô tả tử số và mẫu số.
- **Cảnh báo phân kỳ**: nếu giá trị hiển thị (lấy từ `metrics.json` khi hash khớp) khác với giá trị tính lại từ episode, hộp thoại cảnh báo đỏ để kiểm tra `metrics.json`.
- **Nguồn dữ liệu** (`metrics.json` hay `episodes.jsonl`), trạng thái hash, scope (`all` hoặc chỉ `valid`), và giá trị tính lại.
- **Danh sách episode tử số** (các episode thỏa điều kiện đếm), mỗi episode link tới chi tiết episode; kèm nút mở Episode Explorer đã lọc sẵn theo metric đó.

Metric tổng hợp không có phân tích theo từng episode (vd `yield_latency_p50_ms`) sẽ hiển thị `supported = false` kèm mô tả.

## Data Integrity

| Trường | Ý nghĩa |
|---|---|
| `metric_source` | Cho biết dashboard đang dùng `metrics.json` hay derive từ `episodes.jsonl`. |
| `metrics_hash_valid` | `true` khi hash trong `metrics.json` khớp episode set đang xem. |
| `metric_contract` | Trạng thái contract, denominators, null reasons và violations. |
| `parse_errors` | Lỗi đọc file dữ liệu, nếu có. |

Reference-agent chỉ dùng để kiểm tra evaluator/plumbing. Không báo cáo reference, sample hoặc internal run như performance thật của Vivi/model provider.

## Chọn Run (Run Selector)

Dropdown `FDRC Run` mặc định chỉ hiển thị các run **Benchmark** — tức run có `data_provenance = provider` (kết quả model thật, có thể báo cáo). Đây là "một điểm số thật" duy nhất.

Các run còn lại được gom thành nhóm chẩn đoán và ẩn mặc định. Bật checkbox `Hiện run chẩn đoán` để xem chúng, hiển thị theo `<optgroup>`:

| Nhóm | `data_provenance` | Ý nghĩa |
|---|---|---|
| Kết quả thật (model provider) | `provider` | Kết quả model thật, báo cáo được. |
| Đối chiếu — kiểm bộ chấm | `reference`, `synthetic_reference` | Agent mẫu lý tưởng để kiểm bộ chấm; thường ~100%, không phải hiệu năng thật. |
| Nội bộ — chạy thử khi dev | `internal` | Run thử khi phát triển (`_impl_check_*`, `_plan_check_*`); bỏ đi được. |
| Dữ liệu mẫu | `sample` | Dữ liệu demo/mẫu. |

Run mặc định được chọn là benchmark run mới nhất. Nếu mở dashboard bằng URL trỏ tới một run chẩn đoán, checkbox tự bật để run đó vẫn xuất hiện.

## Chạy Benchmark Từ Dashboard

Nút `Chạy benchmark mới` mở modal tạo run mới. Reference-agent không gọi provider. Preset OpenAI có thể phát sinh chi phí API và phụ thuộc key trong `.env`.

Khuyến nghị vận hành:

1. Dùng existing results để đọc dashboard và xác nhận metrics.
2. Dùng reference-agent để kiểm evaluator/plumbing.
3. Chỉ chạy OpenAI smoke nhỏ khi cần xác nhận provider path thật.
