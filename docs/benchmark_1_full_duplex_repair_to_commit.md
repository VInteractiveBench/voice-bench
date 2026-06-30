# Full-Duplex Repair-to-Commit

# Kiểm thử sửa lệnh trước khi thực thi trong hội thoại song công

## Bối cảnh

**Full-Duplex Repair-to-Commit**, viết tắt là **FDRC**, dùng để đánh giá xem Vivi có xử lý đúng khi người dùng ngắt lời trước khi hệ thống thực thi một hành động hay không.

Trong xe ô tô, người dùng có thể bắt đầu bằng một ý định ban đầu, ví dụ: “dẫn đường đến nhà hàng A”. Khi Vivi đang bắt đầu phản hồi, người dùng có thể ngắt lời để sửa, thu hẹp hoặc hủy yêu cầu, ví dụ: “à không, đến nhà hàng B” hoặc “thôi hủy đi”.

Benchmark này kiểm tra xem Vivi có làm đúng các việc sau không:

* Dừng nói khi người dùng chen ngang.
* Không tiếp tục xử lý ý định cũ.
* Chỉ thực thi ý định cuối cùng sau khi người dùng đã sửa hoặc hủy lệnh.
* Không gọi tool quá sớm trước khi hết khoảng thời gian cho phép người dùng sửa lệnh.

Đây không chỉ là benchmark kiểm thử sửa lỗi qua nhiều lượt hội thoại. Điểm cốt lõi của FDRC là phải có bằng chứng full-duplex, tức là phải chứng minh được theo thời gian rằng:

* Vivi đang nói.
* Người dùng ngắt lời khi Vivi đang nói.
* Vivi đã nhường lời hoặc dừng nói.
* Vivi chưa thực thi hành động nào trước thời điểm được phép commit.

Nói ngắn gọn: FDRC kiểm tra khả năng “nghe người dùng chen ngang và không làm bừa theo lệnh cũ”.

---

## Bài toán cần giải quyết

Rủi ro chính của sản phẩm là **an toàn khi thực thi hành động có side effect**.

Side effect ở đây là các hành động làm thay đổi trạng thái thật, ví dụ:

* Đổi điều hòa.
* Bật hoặc chuyển bài nhạc.
* Gọi điện.
* Đặt tuyến đường điều hướng.
* Mở cửa sổ.
* Thay đổi cài đặt xe.

Nếu người dùng đã sửa hoặc hủy lệnh nhưng Vivi vẫn thực hiện lệnh cũ, thì nhìn trên transcript có thể tưởng là Vivi phản hồi ổn, nhưng trong môi trường cabin thật thì đây là lỗi nghiêm trọng.

| Nhóm lỗi               | Rủi ro sản phẩm                                                              |
| ---------------------- | ---------------------------------------------------------------------------- |
| Thực thi ý định cũ     | Vivi làm theo yêu cầu đã bị người dùng thay thế                              |
| Commit quá sớm         | Vivi gọi tool trước khi hết khoảng thời gian người dùng có thể sửa hoặc hủy  |
| Bỏ qua lệnh hủy        | Người dùng nói hủy nhưng Vivi vẫn thực hiện hành động                        |
| Không nhường lời       | Vivi tiếp tục nói đè lên người dùng hoặc không nhận ra người dùng chen ngang |
| Commit trùng lặp       | Ý định cuối cùng bị thực thi nhiều hơn một lần                               |
| Hiểu sai phần sửa lệnh | Vivi nhận ra có ngắt lời nhưng lại thực thi sai trạng thái cuối cùng         |

Vì vậy, FDRC là benchmark cần có nếu dự án muốn khẳng định đang đánh giá năng lực **full-duplex voice** thật sự, chứ không chỉ đánh giá việc “nghe câu nói rồi gọi tool”.

---

## Phân tích kỹ thuật

### Luồng chạy runtime

| Bước                       | Đường dẫn code                                    | Hành vi                                                                                                        |
| -------------------------- | ------------------------------------------------- | -------------------------------------------------------------------------------------------------------------- |
| 1. Điểm vào                | `run_fdrc.py`                                     | Load `.env`, đọc domain/persona/model, cố định `tick_ms = 200`, và chọn overlay `full_duplex_repair_to_commit` |
| 2. Kiểm tra trước khi chạy | `preflight_validate_assets()`                     | Kiểm tra task và overlay có đúng contract không trước khi chạy provider                                        |
| 3. Phiên adapter           | `OpenAIRealtimeViviAdapter` qua `build_adapter()` | Khởi tạo session realtime/audio với schema tool chính thức của Vivi                                            |
| 4. Audio ý định ban đầu    | `_run_audio_episode()`                            | Sinh và stream `initial_spoken_utterance`, có thêm nhiễu theo `interaction_stress`                             |
| 5. Nhận phản hồi assistant | `_drain_adapter_events()`                         | Nhận song song audio, transcript, tool call từ assistant trong lúc lượt người dùng tiếp theo có thể chồng lên  |
| 6. Thời điểm ngắt lời      | `_timeline_interrupt_ms()`                        | Đọc `user_interrupt_start` từ timeline trong overlay                                                           |
| 7. Audio sửa hoặc hủy lệnh | `_stream_audio(... overlap=True)`                 | Stream `repair_utterance` như lời nói người dùng chen ngang                                                    |
| 8. Thực thi tool           | `MockToolServer.execute()`                        | Chạy các tool call hợp lệ và ghi lại final state một cách deterministic                                        |
| 9. Tạo bằng chứng voice    | `_voice_events_from_normalized()`                 | Tạo voice events và chỉ thêm `assistant_yielded` nếu assistant dừng nói sau khi user đã ngắt lời               |
| 10. Lập lịch tick          | `schedule_timeline()`                             | Sắp xếp voice events và gán `tick = t_ms // 200` cho từng event                                                |
| 11. Đánh giá               | `evaluate_fdrc_episode()`                         | Áp dụng kiểm tra tool/state thông thường cùng các kiểm tra lifecycle của full-duplex                           |

Hiểu đơn giản: benchmark dựng một tình huống có người dùng nói lệnh ban đầu, Vivi bắt đầu trả lời, người dùng chen ngang để sửa hoặc hủy, rồi hệ thống kiểm tra xem Vivi có dừng đúng lúc và chỉ thực thi ý định cuối cùng hay không.

---

### Bộ dữ liệu dùng cho scripted và simulation

FDRC dùng một nguồn chân lý duy nhất cho cả OpenAI và Gemini: `data/jsonl/fdrc_golden_enriched_v2_90.jsonl`. Đây là canonical golden set gồm 90 overlay thuộc namespace `fdrc_v2_*`, bao phủ ba domain chính `automotive`, `navigation`, `media_phone`, ba vùng giọng `north`, `central`, `south`, và các nhóm repair như `entity_repair`, `slot_repair`, `cancel_before_commit`.

Dataset này không chỉ là transcript. Mỗi overlay mô tả đầy đủ môi trường giả lập cần thiết để chấm một episode:

| Nhóm dữ liệu | Field chính | Vai trò trong môi trường giả lập |
| --- | --- | --- |
| Nhận dạng tình huống | `speech_overlay_id`, `base_task_id`, `domain`, `coverage_axes` | Ghép overlay với task nền trong `src/base_task_manifest.json`, chọn schema tool theo domain, và bảo đảm coverage theo lát cắt sản phẩm. |
| Lượt người dùng | `initial_spoken_utterance`, `repair_utterance`, `repair_mode` | Tạo lệnh ban đầu và lệnh sửa/hủy mà provider phải xử lý trong ngữ cảnh full-duplex. |
| Ý định và state chuẩn | `initial_intent`, `final_intent`, `expected_critical_slots`, `expected_final_state` | Xác định ý định cũ phải bị loại bỏ, ý định cuối cùng phải được commit, và trạng thái cuối cùng phải khớp sau khi mock tool chạy. |
| Tool oracle | `expected_tool_calls`, `forbidden_tool_calls` | Xác định tool call hợp lệ và tool call bị cấm; đây là cơ sở để phát hiện commit nhầm ý định cũ, sai tool, sai argument hoặc side effect không được phép. |
| Timeline song công | `voice_timeline`, `voice_assertions` | Mô tả thời điểm user bắt đầu nói, assistant dự kiến bắt đầu nói, user chen ngang, hạn nhường lời, và mốc sớm nhất được phép commit. |

`src/base_task_manifest.json` bổ sung trạng thái nền và mục tiêu task gốc, còn `MockToolServer` dùng domain plus overlay để thực thi tool một cách deterministic. Vì vậy, môi trường giả lập không phụ thuộc vào provider: OpenAI Realtime và Gemini Live nhận cùng nội dung task, cùng schema tool, cùng audio condition, cùng persona, cùng mốc interrupt/commit, và chỉ khác adapter/model đang được đo.

Hai chế độ provider dùng cùng dataset nhưng khác cách phát sinh hành vi người dùng:

| Chế độ run | Cờ runner | Cách tạo môi trường người dùng | Nguồn dữ liệu bắt buộc | Ý nghĩa khi so sánh OpenAI/Gemini |
| --- | --- | --- | --- | --- |
| `scripted` | `--user-simulator off` | Runner synthesize audio trực tiếp từ `initial_spoken_utterance` và `repair_utterance`; thời điểm chen ngang lấy từ `voice_timeline.user_interrupt_start`, sau đó `_await_barge_in()` căn theo lúc assistant thật sự bắt đầu nói để tạo overlap thực tế. | `fdrc_golden_enriched_v2_90.jsonl`, `src/base_task_manifest.json`, persona YAML, audio condition YAML. | Đây là đường đo ổn định nhất vì lượt user cố định; khác biệt kết quả chủ yếu phản ánh adapter/model và transport realtime/audio. |
| `simulation live` | `--user-simulator live` | `UserSimulator` dựng `Scenario` từ overlay: `opening_intent = initial_spoken_utterance`, `true_goal = repair_utterance`, `expected_final_state = expected_final_state`; simulator nghe phản hồi model tại checkpoint semantic rồi quyết định `listen`, `bargein`, `confirm`, hoặc `stop`. | Golden overlay, base task, và guideline trong `data/user_simulator/` nếu bật live simulation. | Đây là đường đo gần hành vi người dùng hơn, nhưng có thêm phương sai từ simulator model; vì vậy phải tách rõ khi so sánh với scripted. |
| `simulation replay` | `--user-simulator replay` | Runner đọc `SimTrace` đã ghi trong `data/simulator_traces`, phát lại `opening`, `repair_text`, và `barge_in_t_ms`; nếu chưa có trace thì fallback sang live và ghi trace mới. | Golden overlay, base task, và trace tương ứng theo overlay/persona/simulator model. | Đây là compromise giữa realism và reproducibility: dynamic trace đã được cố định để OpenAI/Gemini có thể được so sánh trên cùng lượt user. |

Điểm cần giữ nguyên khi báo cáo kết quả là `sim` không phải một golden dataset khác. `fdrc_openai_script`, `fdrc_gemini_script`, `fdrc_openai_sim`, và `fdrc_gemini_sim` đều được chấm trên cùng FDRC golden set; khác biệt nằm ở cách user repair được phát ra và cách timestamp chen ngang được hiện thực hóa trong phiên realtime. Evaluator vẫn dùng `expected_tool_calls`, `forbidden_tool_calls`, `expected_final_state`, `voice_timeline`, và `voice_assertions` từ overlay để bảo toàn cùng một oracle chấm điểm.

---

## Bằng chứng bắt buộc cần có

| Event hoặc field            | Ý nghĩa                                                              |
| --------------------------- | -------------------------------------------------------------------- |
| `assistant_speech_start`    | Thời điểm Vivi bắt đầu nói trước khi người dùng ngắt lời             |
| `user_interrupt_start`      | Thời điểm người dùng bắt đầu sửa hoặc hủy lệnh                       |
| `assistant_yielded`         | Thời điểm Vivi dừng nói sau khi bị ngắt lời                          |
| `tool_commit_allowed_after` | Thời điểm sớm nhất được phép thực thi side effect bằng tool          |
| Tool call `t_ms`            | Timestamp của tool call, dùng để phát hiện commit quá sớm            |
| `expected_tool_calls`       | Các tool call đúng với ý định cuối cùng, bắt buộc phải có            |
| `forbidden_tool_calls`      | Các tool call thuộc ý định cũ, tuyệt đối không được xuất hiện        |
| `final_intent`              | Ý định cuối cùng của người dùng sau khi sửa lệnh, có thể là `cancel` |

Nếu thiếu các field này, benchmark sẽ bị biến thành một bài kiểm thử sửa lệnh nhiều lượt thông thường bằng text, không còn đủ cơ sở để đánh giá hành vi full-duplex thật.

---

## Logic đánh giá

| Kiểm tra                             | Ý nghĩa triển khai                                                                                             |
| ------------------------------------ | -------------------------------------------------------------------------------------------------------------- |
| Tiếp nhận lệnh sửa                   | Mọi tool call tương ứng với ý định cuối cùng đều phải xuất hiện                                                |
| Chặn ý định cũ                       | Không được xuất hiện tool call nào thuộc ý định cũ đã bị thay thế                                              |
| Tuân thủ lệnh hủy                    | Nếu final intent là `cancel`, mọi tool call đều bị coi là lỗi                                                  |
| Độ trễ nhường lời                    | `assistant_yielded - user_interrupt_start` phải nhỏ hơn ngưỡng trong overlay, thường là `700 ms`               |
| Assistant đang nói trước khi bị ngắt | Vivi phải thật sự đang nói trước thời điểm user chen ngang; nếu không thì case này không phải full-duplex thật |
| Ngăn commit sớm                      | Không tool call nào được xảy ra trước `tool_commit_allowed_after`                                              |
| Ngăn commit trùng                    | Tool call đúng với ý định cuối cùng không được lặp lại nhiều lần                                               |
| Trạng thái cuối                      | Final state từ mock tool phải khớp chính xác với expected final state                                          |
| Schema và whitelist                  | Tên tool và tham số phải pass validation theo schema Vivi chuẩn                                                |

Điểm quan trọng nhất: Vivi không chỉ cần trả lời đúng bằng lời nói, mà còn phải gọi đúng tool, đúng thời điểm, đúng một lần, và không để lọt hành động từ ý định cũ.

---

## Các metric chính

| Metric                        | Định nghĩa                                                                        |
| ----------------------------- | --------------------------------------------------------------------------------- |
| `fdrc_pass_at_1`              | Tỷ lệ episode FDRC pass toàn bộ kiểm tra về task, policy, voice và lifecycle      |
| `correction_uptake_rate`      | Tỷ lệ episode mà Vivi tiếp nhận đúng ý định cuối cùng sau khi người dùng sửa lệnh |
| `old_intent_suppression_rate` | Tỷ lệ episode mà ý định cũ bị chặn thành công, không bị commit                    |
| `forbidden_tool_call_rate`    | Tỷ lệ episode có xuất hiện tool call bị cấm thuộc ý định cũ                       |
| `cancel_success_rate`         | Tỷ lệ episode dạng hủy lệnh mà không có side effect nào xảy ra                    |
| `yield_latency_p50_ms`        | Trung vị độ trễ nhường lời                                                        |
| `yield_latency_p95_ms`        | Độ trễ nhường lời tại phân vị 95%                                                 |
| `yield_latency_pass_rate`     | Tỷ lệ episode có độ trễ nhường lời nằm dưới ngưỡng cho phép                       |

Trong đó, các metric quan trọng nhất về sản phẩm là:

* Có commit nhầm ý định cũ không.
* Có commit quá sớm không.
* Có tôn trọng lệnh hủy không.
* Có dừng nói nhanh khi người dùng chen ngang không.

---

## Trạng thái hiện tại

Reference agent hiện đã pass benchmark này. Điều đó cho thấy các thành phần sau đang hoạt động nhất quán:

* Timeline overlay.
* Expected tool calls.
* Forbidden tool calls.
* Bộ evaluator.
* Cơ chế sinh report.

Lần chạy mới nhất với OpenAI realtime surrogate trên domain automotive, persona `vi_north_normal`, và chế độ `interaction_stress` cho kết quả:

```text
fdrc_pass_at_1 = 0.0
```

Các lỗi tập trung chủ yếu ở:

* Chọn sai tool.
* Không pass validation.
* Không tiếp nhận đúng lệnh sửa.
* Độ trễ nhường lời cao.

Kết quả này hữu ích như một smoke test, vì nó chứng minh benchmark có thể phát hiện lỗi full-duplex. Tuy nhiên, không nên hiểu đây là hiệu năng thật của Vivi production, vì hiện tại mới chỉ dùng OpenAI realtime surrogate để giả lập.

Trong quá trình test provider, đã sửa hai lỗi hạ tầng:

1. FDRC summary không còn crash khi episode lỗi bị malformed và thiếu evidence `repair`.
2. Yield latency hiện dùng lần dừng nói đầu tiên của assistant sau `user_interrupt_start`, tránh trường hợp latency âm do lấy nhầm thời điểm dừng nói trước đó.

---

## Khuyến nghị chiến lược

Nên giữ benchmark này như một track lõi.

Lý do là FDRC đánh vào nhóm lỗi rủi ro cao nhất của voice assistant trên xe: **thực thi một hành động đã bị người dùng sửa hoặc hủy trong lúc hội thoại bị ngắt ngang**.

Các ưu tiên triển khai tiếp theo nên là:

1. Chạy một subset có kiểm soát với `gpt-realtime-2` để phân biệt lỗi do giới hạn của model-mini và lỗi do logic benchmark.
2. Lưu cả transcript ASR của lệnh ban đầu và lệnh sửa, để phân loại lỗi rõ hơn: lỗi nghe sai hay lỗi reasoning khi xử lý repair.
3. Yêu cầu log production của Vivi có event ở mức tick, bao gồm `assistant_speech_start`, `user_interrupt_start`, `assistant_yielded`, `tool_commit_allowed_after`, và tool call `t_ms`.
4. Bất kỳ provider path nào gửi text transcript thay vì audio thật chỉ nên được coi là surrogate. Không được tính là benchmark full-duplex production thật.
5. Giữ evaluator deterministic và nghiêm ngặt: đúng final intent, không có side effect từ ý định cũ, không commit sớm, và độ trễ nhường lời phải nằm trong ngưỡng.

---

## Cách hiểu ngắn gọn

FDRC kiểm tra một năng lực rất thực tế của trợ lý giọng nói trên xe:

> Khi người dùng chen ngang để sửa hoặc hủy lệnh, Vivi có dừng lại kịp thời, bỏ ý định cũ, và chỉ thực hiện đúng ý định cuối cùng hay không?

Nếu không có FDRC, benchmark voice rất dễ chỉ đo được khả năng nhận diện lệnh và gọi tool, nhưng bỏ sót rủi ro nguy hiểm nhất trong môi trường thật: **người dùng đã đổi ý nhưng hệ thống vẫn hành động theo lệnh cũ**.
