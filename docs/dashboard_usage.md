# Hướng dẫn sử dụng Dashboard Vivi Voice Bench

## Context

Dashboard `Vivi Voice Bench` là công cụ local để quan sát và chạy hai benchmark chính:

| Benchmark | Mục đích |
|---|---|
| `Text-to-Voice Capability Retention` | Đo mức Vivi giữ được năng lực từ text baseline sang voice, đặc biệt ở critical slots, tool calls, arguments và final state. |
| `Full-Duplex Repair-to-Commit` | Đo khả năng nhường lời khi user chen ngang, tiếp nhận lệnh sửa hoặc hủy, chặn ý định cũ và chỉ commit ý định cuối cùng. |

Dashboard đọc kết quả từ:

```text
results/<run_name>/metrics.json
results/<run_name>/episodes.jsonl
```

## Cách chạy

```powershell
$env:PYTHONPATH='src;.'
python -m speech_interaction.dashboard --host 127.0.0.1 --port 8765
```

Mở:

```text
http://127.0.0.1:8765
```

## Tính trung thực dữ liệu

Dashboard không tự tạo số liệu. Nó đọc đúng dữ liệu runner đã ghi, nhưng phân loại rõ nguồn dữ liệu để tránh hiểu nhầm.

| Nguồn dữ liệu | Cách nhận biết | Có dùng để báo cáo performance không? |
|---|---|---|
| Provider/model thật | Episode có `agent` hoặc `model`, ví dụ `openai_as_vivi`, `gpt-realtime-mini`, `gpt-4o-mini`. | Có thể dùng nếu run scope đúng. |
| Reference-agent tổng hợp | Episode không có `agent/model`, thường pass 100%. | Không. |
| Internal/sample | Run có pattern `_plan_check_*`, `_impl_check_*`, `*_sample`. | Không. |

Nếu dashboard hiển thị cảnh báo provenance, không dùng run đó để kết luận performance model thật.

## Luồng sử dụng chuẩn

1. Chọn `Benchmark`.
2. Chọn `Lần chạy`.
3. Đọc header run: track, status, episode count, source, updated time.
4. Đọc cảnh báo provenance nếu có.
5. Đọc KPI chính theo benchmark track.
6. Dùng `Phân rã tỷ lệ pass` và `Phân loại lỗi` để xác định lỗi tập trung ở đâu.
7. Dùng `Điều tra episode` và quick filters để chọn episode cần điều tra.
8. Mở detail episode theo tab: `Tóm tắt`, `Hội thoại`, `Dòng thời gian`, `Tool & trạng thái`, `Bằng chứng`, `JSON thô`.

## Navigation bên trái

Sidebar chỉ phục vụ điều hướng và lọc kết quả:

| Thành phần | Ý nghĩa |
|---|---|
| `Benchmark` | Chọn một trong hai bài test chính. |
| `Lần chạy` | Chọn run phù hợp với benchmark đang chọn. |
| `Domain` | Lọc theo domain. |
| `Mode` | Lọc theo chế độ đầu vào. |
| `Loại lỗi` | Lọc theo failure taxonomy. |
| `Kết quả` | Lọc tất cả, pass hoặc fail. |
| `Bộ lọc nâng cao` | Lọc thêm theo accent region, speech speed và audio condition. |

Nguồn nhãn của bộ lọc nâng cao:

| Filter | Field trong episode | Source-of-truth |
|---|---|---|
| `Vùng giọng` | `accent_region` | `speech_interaction/personas/*.yaml` |
| `Tốc độ nói` | `speech_speed` | `speech_interaction/personas/*.yaml`, gồm `slow`, `normal`, `fast` |
| `Điều kiện âm thanh` | `audio_condition_id` | `speech_interaction/audio_conditions/*.yaml`, ví dụ `clean`, `cabin_noise`, `interaction_stress` |

Nếu thấy `clean` hoặc `cabin_noise`, đó là điều kiện âm thanh chứ không phải tốc độ nói. Dashboard hiện hiển thị nhãn field kỹ thuật trong ngoặc để tránh nhầm lẫn.

Các hành động global nằm ở header:

| Hành động | Ý nghĩa |
|---|---|
| `Chạy benchmark mới` | Mở modal chạy benchmark mới. |
| `Làm mới` | Quét lại thư mục `results/`. |

## Chạy benchmark mới

Nút `Chạy benchmark mới` ở header mở modal riêng để tránh trộn lẫn thao tác xem kết quả và thao tác tạo run mới.

| Preset | Hành vi |
|---|---|
| `Retention reference-agent` | Chạy `run_voice_retention.py --reference-agent`; không gọi provider. |
| `Retention OpenAI realtime` | Chạy `run_voice_retention.py --agent openai_realtime`; có thể gọi provider thật. |
| `FDRC reference-agent` | Chạy `run_fdrc.py --reference-agent`; không gọi provider. |
| `FDRC OpenAI realtime` | Chạy `run_fdrc.py --agent openai_realtime`; có thể gọi provider thật. |

Modal hiển thị cảnh báo rõ vì preset OpenAI có thể phát sinh chi phí provider/model.

Dashboard cũng hiển thị ước lượng số episode trước khi chạy, tính từ số overlay theo domain trong `speech_task_overlays.jsonl`, số persona được chọn và số mode audio của benchmark.

## KPI theo benchmark

### Text-to-Voice Retention

KPI chính:

| Metric | Ý nghĩa |
|---|---|
| `Pass tổng` | Tỷ lệ episode pass toàn bộ tiêu chí. |
| `Giữ năng lực voice` | Cabin voice pass chia cho text baseline pass. |
| `Đúng critical slot` | Tỷ lệ slot quan trọng được giữ đúng. |
| `Pass voice cabin` | Tỷ lệ pass trong điều kiện cabin voice. |
| `Khớp tool` | Tỷ lệ gọi đúng tool expected. |

### Full-Duplex Repair-to-Commit

KPI chính:

| Metric | Ý nghĩa |
|---|---|
| `Pass FDRC` | Tỷ lệ episode FDRC pass toàn bộ tiêu chí. |
| `P50 nhường lời` | Trung vị độ trễ nhường lời sau khi user chen ngang. |
| `P95 nhường lời` | Tail latency của nhường lời. |
| `Vi phạm policy` | Tỷ lệ episode vi phạm policy. |
| `Khớp trạng thái` | Tỷ lệ final state khớp expected. |

Các metric phụ nằm trong `Chỉ số phụ`.

## Diagnostic panels

| Khu vực | Ý nghĩa |
|---|---|
| `Phân rã tỷ lệ pass` | Chọn dimension: domain, mode, accent region, speech speed hoặc audio condition. |
| `Các lỗi ghi nhận` | Đếm số episode có từng loại lỗi, kèm tỷ lệ trên tổng run và mô tả ngắn. Đây không phải điểm số. |
| `Chẩn đoán chính` | Retention hiển thị degradation/slot; FDRC hiển thị top slowest yield latency episodes. |
| `Tóm tắt độ trễ` | Bảng `count`, `min`, `p50`, `p95`, `max` cho latency có trong episode logs. |

Trong `Các lỗi ghi nhận`, số như `5 episode` nghĩa là có 5 episode trong run chứa loại lỗi đó. Một episode fail có thể bị tính vào nhiều loại lỗi nếu nó vừa sai tool, vừa sai argument hoặc vừa sai final state, nên tổng các dòng lỗi có thể lớn hơn số episode fail.

## Điều tra episode

Quick filters:

| Filter | Ý nghĩa |
|---|---|
| `Chỉ fail` | Chỉ xem episode fail. |
| `Vi phạm policy` | Chỉ xem episode có policy violation. |
| `Sai critical slot` | Chỉ xem retention episode sai critical slot. |
| `Độ trễ cao` | Chỉ xem episode có yield latency cao. |
| `Sai tool` | Chỉ xem episode sai tool. |

Các cột thay đổi theo benchmark track. Retention ưu tiên critical slot, tool, argument và state. FDRC ưu tiên yield latency, old intent blocked, correction uptake và tool call.

## Episode detail

| Tab | Ý nghĩa |
|---|---|
| `Tóm tắt` | Kết luận ngắn, pass/fail, lỗi chính, domain, mode, persona/accent/speed và latency. |
| `Hội thoại` | User transcript và assistant transcript. |
| `Dòng thời gian` | Mốc thời gian quan trọng: interrupt, yielded, tool call, commit allowed. |
| `Tool & trạng thái` | Tool calls, tool results, trạng thái ban đầu và trạng thái cuối. |
| `Bằng chứng` | Retention evidence hoặc FDRC repair evidence tùy benchmark. |
| `JSON thô` | JSON đầy đủ, chỉ dùng khi debug sâu. |

## API

| Endpoint | Ý nghĩa |
|---|---|
| `GET /api/runs` | Liệt kê run trong `results/`. |
| `GET /api/run-presets` | Liệt kê preset chạy benchmark. |
| `POST /api/benchmark-runs` | Khởi động benchmark mới bằng preset. |
| `GET /api/benchmark-runs/{job_id}` | Xem trạng thái job. |
| `GET /api/runs/{run_id}/summary` | Metrics, pass/fail counts, failure counts, latency summary. |
| `GET /api/runs/{run_id}/episodes` | Bảng episode, hỗ trợ filter chính. |
| `GET /api/runs/{run_id}/episodes/{episode_id}` | Chi tiết forensic của một episode. |
