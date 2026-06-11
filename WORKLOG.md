# WORKLOG

## Context

File này ghi nhật ký tiến độ hằng ngày cho dự án `Vivi-tauVoice-CarBench-VN`, tập trung vào các quyết định sản phẩm, artifact kỹ thuật đã tạo, kết quả evaluation, và các rủi ro còn tồn tại của benchmark tiếng Việt trong ngữ cảnh ô tô.

## Nhật ký tiến độ

### 07/06/2026

- Chốt 2 benchmark trọng tâm để xây dựng thay vì mở rộng quá rộng sang benchmark hội thoại tổng quát:
  - **Text-to-Voice Retention**: Benchmark Giữ năng lực từ văn bản sang giọng nói, đo mức suy giảm năng lực task-grounded khi chuyển cùng một tác vụ từ text sang voice tiếng Việt.
  - **Full-Duplex Repair-to-Commit**: Benchmark Song công Sửa lệnh trước khi Chốt hành động, đo khả năng agent nhường lời, tiếp nhận lệnh sửa hoặc hủy, loại bỏ ý định cũ, và chỉ commit theo ý định cuối cùng.
- Xác định benchmark không chỉ đo ASR hoặc transcript similarity, mà phải chấm theo tool call, tham số tool, trạng thái cuối, policy compliance, critical spoken slots, và bằng chứng tương tác giọng nói.
- Chốt phạm vi sản phẩm ban đầu xoay quanh bối cảnh Vivi trên xe VinFast, ưu tiên các tác vụ có giá trị thực tế trong cabin thay vì domain giả lập độc lập.

### 08/06/2026

- Tạo các tập noise và cấu trúc dữ liệu âm thanh ban đầu để phục vụ voice benchmark, bao gồm các nhóm noise dạng burst, continuous, cabin sound, engine sound, và cache noise đã xử lý.
- Bắt đầu xây dựng benchmark/eval với domain `automotive` làm domain trọng tâm ban đầu để kiểm tra end-to-end trước khi mở rộng.
- Bổ sung tài liệu user simulator cho kịch bản text, tool, và voice nhằm chuẩn hóa cách sinh episode và giảm độ lệch khi đánh giá agent.
- Thiết lập nền dữ liệu ban đầu theo hướng tái sử dụng task/policy/db của tau2 nhưng ràng buộc lại cho bề mặt đánh giá giọng nói.

### 10/06/2026

- Mở rộng dữ liệu domain từ `automotive` sang `navigation` và `media_phone`, tạo nền logical task cho MVP đa miền.
- Chuẩn hóa task nguồn qua `speech_interaction/base_task_manifest.json`, liên kết logical task với các overlay giọng nói.
- Tạo `speech_interaction/speech_task_overlays.jsonl` với 60 overlay, gồm 30 overlay cho Text-to-Voice Retention và 30 overlay cho Full-Duplex Repair-to-Commit.
- Xây dựng các audio condition chính: `clean`, `cabin_noise`, và `interaction_stress`, phục vụ đo năng lực trong điều kiện sạch, cabin thực tế, và tương tác có áp lực.
- Xây dựng 9 persona tiếng Việt theo vùng giọng và tốc độ nói: Bắc, Trung, Nam kết hợp với slow, normal, fast.
- Bổ sung bộ evaluator cốt lõi cho retention, full-duplex, critical slot, voice event, tool schema, tool scope, và failure taxonomy.

### 11/06/2026

- Hoàn thiện các runner CLI chính:
  - `run_text_baseline.py` để chấm baseline text.
  - `run_voice_retention.py` để chấm voice sạch và voice cabin.
  - `run_fdrc.py` để chấm full-duplex repair-to-commit với tick 200 ms.
  - `generate_voice_report.py` để tổng hợp kết quả và failure report.
- Hoàn thiện tầng orchestration cho agent thật/surrogate, gồm OpenAI text adapter, OpenAI realtime adapter, audio cache, TTS client, noise mixer, tick scheduler, event logger, mock tool server, và full-duplex orchestrator.
- Bổ sung dashboard nội bộ trong `speech_interaction/dashboard` để đọc metrics, episode logs, và failure artifacts.
- Chạy kiểm tra reference-agent cho các track chính và ghi kết quả vào `results/check_text_reference`, `results/check_voice_reference`, và `results/check_fdrc_reference`.
- Chạy thử OpenAI/surrogate trên automotive:
  - Text baseline với `gpt-4o-mini`: `pass_at_1 = 0.60`, `critical_slot_accuracy = 1.00`, `tool_validation_error_rate = 0.30`.
  - Voice clean/cabin với realtime mini: `pass_at_1 = 0.10`, `clean_voice_pass_at_1 = 0.20`, `cabin_voice_pass_at_1 = 0.00`, `critical_slot_accuracy = 0.1818`.
  - FDRC với realtime mini: `fdrc_pass_at_1 = 0.00`, `old_intent_suppression_rate = 0.875`, `forbidden_tool_call_rate = 0.125`, `yield_latency_p50_ms = 2548`, `yield_latency_pass_rate = 0.375`.
- Viết tài liệu kỹ thuật trong `README.md`, `FLOW.md`, `speech_interaction/README.md`, và `speech_interaction/benchmark_scope.md` để mô tả phạm vi, contract dữ liệu, luồng runner, evaluator, và cách chạy benchmark.
- Bổ sung test coverage cho voice benchmark và audio pipeline trong `tests/test_vivi_voice_benchmark.py` và `tests/test_vivi_audio_pipeline.py`.

## Trạng thái hiện tại

| Hạng mục | Trạng thái | Ghi chú kỹ thuật |
|---|---|---|
| Product scope | Đã chốt MVP | MVP tập trung vào Text-to-Voice Retention và Full-Duplex Repair-to-Commit cho in-car Vietnamese voice interaction. |
| Domain coverage | Đã có nền đa miền | `automotive`, `navigation`, và `media_phone` đã có task/policy/db hoặc task scaffold tương ứng. |
| Speech overlays | Đã có 60 overlay | 30 retention overlay và 30 FDRC overlay đã được ghi trong `speech_task_overlays.jsonl`. |
| Personas | Đã có 9 persona | Bao phủ 3 vùng giọng và 3 tốc độ nói. |
| Audio conditions | Đã có 3 condition chính | `clean`, `cabin_noise`, và `interaction_stress`. |
| Noise assets | Đã có nhiều nguồn noise | Có burst noise, continuous noise, cabin sound, engine sound, và cache noise đã xử lý. |
| Evaluation runners | Đã có runner end-to-end | Text baseline, voice retention, FDRC, và report generator đã tồn tại. |
| Agent integration | Đã có adapter | Có OpenAI text/realtime adapter và mock tool server để chạy surrogate hoặc kiểm tra hạ tầng. |
| Reporting | Đã có artifact kết quả | `results/` đã có metrics, episodes, smoke report, reference runs, và OpenAI runs. |
| Dashboard | Đã có scaffold | Có FastAPI service và static frontend trong `speech_interaction/dashboard`. |
| Test coverage | Đã có test chuyên biệt | Có test cho benchmark voice, audio pipeline, dashboard, orchestrator, runner, và các domain cũ của tau2. |

## Vấn đề còn mở

- Kết quả voice cabin hiện còn thấp trong automotive OpenAI run, đặc biệt `cabin_voice_pass_at_1 = 0.00`, cần phân tích thêm theo transcript quality, tool schema mismatch, audio mixing, và realtime turn-taking.
- FDRC chưa đạt pass trong run surrogate hiện tại, với rủi ro chính nằm ở correction uptake, cancel handling, yield latency, và tool validation.
- `tool_validation_error_rate` trong text và voice run vẫn đáng kể, cần rà soát tương thích giữa schema Vivi, prompt tool-use, và output của adapter.
- Cần tách rõ kết quả reference-agent dùng để kiểm tra hạ tầng với kết quả model thật để tránh báo cáo nhầm performance oracle như performance agent.
- Cần tiếp tục chuẩn hóa tên domain `media_phone` so với cách gọi sản phẩm `media` để giảm nhầm lẫn trong báo cáo và tài liệu.

## Công việc tiếp theo

- Phân tích failure report theo từng failure type để xác định lỗi do benchmark contract, adapter, audio condition, hay năng lực model.
- Hoàn thiện báo cáo định lượng cho từng track: text baseline, clean voice, cabin voice, và FDRC.
- Mở rộng evaluation từ automotive sang toàn bộ domain MVP sau khi automotive pipeline ổn định.
- Rà soát lại critical slots cho voice overlay để bảo đảm slot vừa đủ nghiêm ngặt nhưng không phạt sai các biến thể nói tự nhiên hợp lệ.
- Chuẩn hóa dashboard để phục vụ demo nhanh: chọn run, xem metrics, xem episode failure, và lọc theo domain/condition/persona.
