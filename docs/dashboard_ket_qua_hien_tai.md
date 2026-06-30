# Dashboard: Diễn Giải Kết Quả Hiện Có

## Context

Tài liệu này giải thích các số liệu hiện có trên dashboard `Vivi Voice Bench`, dựa trên artifact đang nằm trong `results/` tại thời điểm tài liệu được tạo. Dashboard không tự sinh điểm benchmark; nó đọc `episodes.jsonl` và `metrics.json`, kiểm tra `episode_set_hash`, sau đó hiển thị metric theo từng benchmark track.

Phạm vi phân tích tập trung vào hai track đang được dashboard hỗ trợ trực tiếp:

| Track | Mục tiêu đo lường | Dataset/run hiện có trên dashboard |
|---|---|---|
| `full_duplex_repair_to_commit` | Đo năng lực nhường lời khi user chen ngang, tiếp nhận lệnh sửa hoặc hủy, chặn ý định cũ, và chỉ commit ý định cuối cùng. | Provider FDRC 90 episode cho OpenAI/Gemini ở các chế độ `script` và `sim`, cộng với reference-agent 90 episode. |
| `voice_policy_command_gating` | Đo quyết định `execute`, `clarify`, `refuse`, hoặc `defer` theo policy và trạng thái xe. | Provider Gemini Live 24 episode, cộng với reference-agent 72 episode. |

Tất cả summary chính được trích từ logic `src.dashboard.service.DashboardStore`, tức cùng lớp dịch vụ mà API dashboard sử dụng. Các run được nêu trong tài liệu này có `metrics_hash_valid = true` và `metric_source = episodes.jsonl`, nghĩa là số hiển thị khớp với tập episode đang được đọc hoặc đã được tính lại trực tiếp từ episode logs.

## Problem Statement

Dashboard hiện đã đủ để trả lời câu hỏi "hệ thống đang fail ở đâu" nhưng chưa đủ để tuyên bố "mô hình đã sẵn sàng sản phẩm". Lý do là các kết quả provider thật còn thấp ở FDRC, một số run chưa đạt ngưỡng reportability do validity dưới 90%, và coverage Policy Gating provider mới ở mức smoke 24 episode.

Do đó, cách đọc đúng là:

| Loại số liệu | Cách diễn giải đúng | Rủi ro nếu đọc sai |
|---|---|---|
| Reference-agent đạt 100% | Evaluable contract, evaluator, dashboard, và plumbing dữ liệu đang nhất quán. | Không được xem là năng lực thật của model/provider. |
| Provider FDRC operational pass thấp | Model/provider chưa xử lý ổn định repair-to-commit trong tình huống song công. | Nếu chỉ nhìn strict pass hoặc raw pass có thể bỏ qua nguyên nhân vận hành cụ thể. |
| Validity dưới 90% | Run chưa đủ điều kiện báo cáo headline performance chính thức. | So sánh trực tiếp với run reportable sẽ tạo kết luận sai. |
| Policy Gating forbidden tool call bằng 0% | Tín hiệu an toàn tích cực: provider không gọi tool bị cấm trong sample hiện có. | Không đủ để kết luận policy compliance tổng thể vì vẫn có lỗi tool selection và argument. |

## Technical Deep-Dive

### 1. FDRC: Kết quả provider hiện có

FDRC dùng `operational_fdrc_pass_at_1` làm chỉ số chất lượng mô hình thực dụng hơn `performance_fdrc_pass_at_1`. Operational pass cho phép một số khác biệt không blocking sau chuẩn hóa tool/argument/state; strict pass yêu cầu không còn bất kỳ failure type nào, nên chủ yếu dùng để soi lỗi.

| Run | Provider/model | Episode | Validity | Operational FDRC pass | Strict pass trên valid episodes | Yield pass | Yield p50 / p95 | Nhận định kỹ thuật |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| `fdrc_gemini_script` | Gemini native audio | 90 | 98.89% | 20.00% | 4.49% | 0.00% | 2493 ms / 4512 ms | Run reportable tốt nhất hiện tại theo operational pass, nhưng latency nhường lời chưa đạt và tool match chỉ 6.67%. |
| `fdrc_openai_script` | GPT realtime mini | 90 | 88.64% | 16.67% | `null` | 70.00% | 379 ms / 6600 ms | Latency median tốt, nhưng validity dưới 90% làm headline/strict official bị null; 46 infra/transport-related episodes làm giảm độ tin cậy báo cáo. |
| `fdrc_openai_sim` | GPT realtime mini | 90 | 100.00% | 7.78% | 0.00% | 2.22% | 3178.5 ms / 4035 ms | Evidence hợp lệ đầy đủ nhưng repair uptake, tool selection, và latency đều yếu. |
| `fdrc_gemini_sim` | Gemini native audio | 90 | 96.67% | 6.67% | 2.30% | 16.85% | 889 ms / 7929 ms | Validity đủ báo cáo, nhưng tail latency và tool selection là điểm nghẽn chính. |
| `fdrc_reference` | Reference-agent | 90 | 100.00% | 100.00% | 100.00% | 100.00% | 400 ms / 400 ms | Chứng minh evaluator và dashboard có thể chấm pass đầy đủ khi log đúng contract. |

Các lỗi FDRC nổi bật theo dashboard:

| Failure type | Tín hiệu từ run provider | Ý nghĩa sản phẩm |
|---|---|---|
| `TOOL_SELECTION_ERROR` | Là primary failure lớn nhất ở cả bốn provider FDRC run. | Agent thường không gọi đúng tool cuối cùng sau repair, làm hành động xe sai hoặc không xảy ra. |
| `CORRECTION_NOT_UPTAKEN` | Xuất hiện 82/90 ở `fdrc_openai_sim`, 83/90 ở `fdrc_gemini_sim`, 84/90 ở `fdrc_gemini_script`. | Agent chưa nội hóa lệnh sửa sau khi user chen ngang; đây là vấn đề cốt lõi của FDRC. |
| `YIELD_LATENCY_TOO_HIGH` | Rất cao ở `fdrc_openai_sim` và latency pass bằng 0% ở `fdrc_gemini_script`. | Trải nghiệm song công chưa đạt yêu cầu cảm nhận người dùng, đặc biệt khi assistant tiếp tục nói sau interrupt. |
| `FINAL_STATE_MISMATCH` | Xuất hiện trên đa số provider FDRC run. | Dù có thể gọi tool, trạng thái cuối vẫn chưa nhất quán với intent cuối cùng. |
| `MISSING_OBSERVED_EVENT` / `INVALID_EVIDENCE` | Đặc biệt ảnh hưởng các run có transport/evidence issue. | Chất lượng logging và evidence pipeline vẫn là tiền đề bắt buộc trước khi benchmark hóa kết quả. |

### 2. Policy Gating: Kết quả provider hiện có

Policy Gating hiện có một provider run chính:

| Run | Episode | Pass tổng | Policy compliance | Forbidden tool call | Clarification precision / recall | State-conditioned accuracy | Final state correctness | Response honesty | Tool argument accuracy |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `policy_gating_gemini_live` | 24 | 50.00% | 66.67% | 0.00% | 60.00% / 100.00% | 100.00% | 70.83% | 83.33% | 23.81% |
| `policy_gating_reference` | 72 | 100.00% | 100.00% | 0.00% | 100.00% / 100.00% | 100.00% | 100.00% | 100.00% | 100.00% |

Diễn giải kỹ thuật:

| Metric | Tín hiệu hiện tại | Kết luận |
|---|---|---|
| `forbidden_tool_call_rate = 0.00%` | Không thấy provider gọi tool bị cấm trong sample 24 episode. | Đây là tín hiệu an toàn tích cực, nhưng sample còn nhỏ. |
| `policy_compliance_rate = 66.67%` | 1/3 episode vẫn chọn sai quyết định policy-level. | Decision policy chưa ổn định đủ để xem là production-ready. |
| `state_conditioned_decision_accuracy = 100.00%` | Các cặp phụ thuộc trạng thái xe trong sample được phân biệt đúng. | Model có tín hiệu hiểu state, nhưng vẫn fail ở tool/action layer. |
| `tool_argument_accuracy = 23.81%` | Argument đúng rất thấp trên execute cases. | Product risk nằm ở hành động sai tham số, không chỉ ở quyết định có gọi tool hay không. |

### 3. Những việc đã làm được

| Hạng mục | Trạng thái | Giá trị kỹ thuật/sản phẩm |
|---|---|---|
| Dashboard đọc artifact chuẩn | Đã có | Đọc `results/<run>/episodes.jsonl` và `metrics.json`; có kiểm tra hash để tránh số liệu stale. |
| Tách provenance run | Đã có | Phân biệt provider, reference, internal, sample; giảm nguy cơ báo cáo nhầm số reference thành performance thật. |
| Hai benchmark trọng tâm | Đã có | FDRC đo năng lực song công repair-to-commit; Policy Gating đo policy/state decision. |
| Metric catalog theo nhóm | Đã có | Chia `Overview`, `Tool / State`, `Policy`, `FDRC`, `Latency`, `Contract / Data Quality`; thuận tiện cho forensic debugging. |
| Drilldown metric-to-episode | Đã có cho nhiều metric | Người đọc có thể đi từ KPI xuống danh sách episode lỗi để xác định nguyên nhân cụ thể. |
| FDRC timeline | Đã có | Hiển thị interrupt, yield, repair window, tool call, commit gate; phù hợp debug lỗi song công. |
| Reference-agent contract | Đã có | Reference đạt 100% trên FDRC và Policy Gating, xác nhận evaluator có đường pass hợp lệ. |

### 4. Thực trạng hệ thống

| Trục đánh giá | Hiện trạng | Đánh giá theo Iron Triangle |
|---|---|---|
| Reliability | FDRC provider pass thấp; Policy Gating pass trung bình; reference pass 100%. | Reliability của evaluator tốt hơn reliability của agent/provider hiện tại. |
| Latency | FDRC yield latency không ổn định; một số run có p95 rất cao. | Latency là blocker trực tiếp cho trải nghiệm full-duplex vì user interrupt cần phản hồi gần tức thời. |
| Scalability | Dashboard đã đọc nhiều run và có nhóm provenance, nhưng provider coverage chưa đồng đều. | Hạ tầng đủ để mở rộng số run; dữ liệu hiện tại chưa đủ để làm leaderboard sản phẩm cuối. |
| Cost-to-serve | Có thể chạy reference không tốn provider, nhưng provider realtime/audio có chi phí API. | Nên dùng reference/smoke để kiểm pipeline trước, chỉ chạy provider khi cần dữ liệu báo cáo. |
| User friction | Dashboard có episode explorer và timeline, nhưng người mới vẫn cần tài liệu diễn giải. | Tài liệu này giảm friction đọc KPI, nhưng UX vẫn cần benchmark summary tự động hơn. |

## Strategic Recommendations

### 1. Không báo cáo FDRC như năng lực production cho đến khi đạt ngưỡng tối thiểu

FDRC nên có điều kiện báo cáo chính thức trước khi đưa vào product decision:

| Gate | Ngưỡng đề xuất | Lý do |
|---|---:|---|
| `fdrc_validity_rate` | >= 90% | Dưới ngưỡng này, headline/strict metrics có thể bị null hoặc thiếu đại diện. |
| `operational_fdrc_pass_at_1` | >= 80% cho smoke, >= 90% cho release candidate | Repair-to-commit là workflow an toàn; pass thấp không thể bù bằng UX copy. |
| `yield_latency_pass_rate` | >= 95% | Nhường lời chậm phá vỡ kỳ vọng song công ngay cả khi tool cuối đúng. |
| `primary_failure_counts.TOOL_SELECTION_ERROR` | Xu hướng giảm liên tục qua run | Tool sai là lỗi hành động, có rủi ro cao hơn lỗi diễn đạt. |

### 2. Ưu tiên sửa FDRC theo thứ tự tác động

| Ưu tiên | Việc cần cải tiến | Cơ sở dữ liệu hiện tại | Tác động kỳ vọng |
|---:|---|---|---|
| 1 | Củng cố state machine interrupt-yield-repair-commit. | `CORRECTION_NOT_UPTAKEN`, `TOOL_SELECTION_ERROR`, và `YIELD_LATENCY_TOO_HIGH` chiếm tỷ trọng lớn. | Tăng operational pass và giảm lỗi commit ý định cũ. |
| 2 | Chuẩn hóa evidence logging realtime/audio. | Một số run có `MISSING_OBSERVED_EVENT`, `INVALID_EVIDENCE`, hoặc transport issue. | Tăng validity và giảm số run không reportable. |
| 3 | Tách rõ `native_yield` và `client_cancel_yield`. | Latency phản ánh hai tầng khác nhau: năng lực model/provider và năng lực orchestration. | Tránh kết luận sai khi so sánh provider. |
| 4 | Tăng kiểm thử theo domain/persona/audio condition. | Hiện có 90 episode FDRC provider nhưng chưa đủ phân tích confidence interval theo lát cắt nhỏ. | Phát hiện domain-specific regression trước khi báo cáo tổng. |

### 3. Nâng Policy Gating từ smoke lên benchmark đáng tin cậy

| Khoảng trống | Cải tiến đề xuất | Lý do |
|---|---|---|
| Provider sample mới 24 episode | Chạy đủ canonical policy set với nhiều persona/provider. | 24 episode đủ debug, chưa đủ kết luận sản phẩm. |
| Argument accuracy thấp | Thêm repair prompt/tool schema guardrail và evaluator drilldown cho từng argument. | Quyết định đúng nhưng argument sai vẫn tạo hành động xe sai. |
| Compliance 66.67% | Tách lỗi decision policy khỏi lỗi execution/tool. | Cần biết model sai ở policy reasoning hay ở tool invocation layer. |
| Forbidden tool call 0% | Giữ metric này làm safety KPI bắt buộc. | Đây là tín hiệu tốt nhưng phải được duy trì khi tăng coverage. |

### 4. Cải thiện dashboard và quy trình báo cáo

| Hạng mục | Đề xuất | Outcome |
|---|---|---|
| Benchmark summary tự động | Sinh một `benchmark_report.md` từ dashboard summary cho từng run. | Giảm thao tác thủ công khi bàn giao kết quả. |
| Confidence interval | Thêm Wilson interval hoặc bootstrap CI cho pass rates. | Tránh overfit kết luận trên sample nhỏ. |
| Regression tracking | Lưu baseline provider theo ngày/model/yield mode. | Cho phép phát hiện cải thiện hoặc suy giảm qua thời gian. |
| Leaderboard có gate | Chỉ đưa run vào leaderboard khi provenance là provider, hash valid, validity đủ ngưỡng, và episode count đủ lớn. | Giảm nguy cơ so sánh sai giữa reference, smoke, internal và provider thật. |
| Failure prioritization | Thêm view Pareto theo primary failure và domain/persona/audio condition. | Tập trung effort vào lỗi có ảnh hưởng lớn nhất. |

## Kết luận

Dashboard hiện đã đạt vai trò forensic console: nó cho biết evaluator hoạt động đúng, dữ liệu có provenance, hash contract được kiểm soát, và từng KPI có thể drilldown xuống episode. Tuy nhiên, kết quả provider hiện tại cho thấy FDRC vẫn là blocker chính: operational pass cao nhất mới đạt 20.00%, yield latency còn yếu, và lỗi tool selection/correction uptake xuất hiện dày đặc. Policy Gating có tín hiệu an toàn tốt ở forbidden tool call 0.00%, nhưng compliance 66.67% và argument accuracy 23.81% cho thấy chưa nên xem là hoàn tất.

Định hướng đúng là tiếp tục dùng dashboard như công cụ đo và debug, không dùng các số hiện tại làm tuyên bố production readiness. Trước khi báo cáo ra ngoài, cần tăng coverage provider, bảo đảm validity >= 90%, chuẩn hóa evidence realtime/audio, và thiết lập release gates rõ ràng cho FDRC lẫn Policy Gating.
