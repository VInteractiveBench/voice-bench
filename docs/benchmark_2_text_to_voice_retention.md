# Text-to-Voice Capability Retention

# Đánh giá khả năng giữ nguyên năng lực từ text sang voice

## Bối cảnh

**Text-to-Voice Capability Retention** dùng để đánh giá xem Vivi có giữ được năng lực xử lý tác vụ khi cùng một ý định của người dùng được chuyển từ **đầu vào dạng text** sang **đầu vào giọng nói tiếng Việt** hay không.

Benchmark này **không phải** là bài test ASR đơn thuần, không phải bài test độ tự nhiên của giọng nói, và cũng không phải benchmark chatbot chung chung. Mục tiêu của nó là đo xem khi người dùng nói bằng giọng Việt, hệ thống có còn giữ đúng các phần mà text baseline đã làm được hay không, bao gồm:

* Đúng trajectory gọi tool chính thức của Vivi.
* Đúng tham số tool.
* Đúng final state.
* Giữ được các critical slot quan trọng.
* Giao tiếp lại với người dùng đúng yêu cầu.

Track này cần tồn tại vì một trợ lý trong xe có thể pass benchmark gọi tool bằng text, nhưng vẫn fail khi gặp điều kiện giọng nói thực tế. Với tiếng Việt, các yếu tố như giọng vùng miền, tốc độ nói, tiếng ồn trong cabin, hoặc nhập nhằng ASR có thể làm sai các slot quan trọng, ví dụ:

* Nhiệt độ điều hòa.
* Vị trí ghế.
* Cửa sổ cần điều khiển.
* Điểm đến điều hướng.
* Bài hát, nghệ sĩ, playlist.
* Tên người cần gọi.

Điểm quan trọng là: lỗi voice không nhất thiết nằm ở khả năng reasoning của model. Model có thể hiểu task nếu nhập bằng text, nhưng khi chuyển sang voice, thông tin đầu vào đã bị sai hoặc mất trước khi tới bước gọi tool.

---

## Bài toán cần giải quyết

Câu hỏi sản phẩm cốt lõi là:

> Nếu Vivi làm được một tác vụ bằng text, thì khi người dùng nói tác vụ đó bằng giọng nói sạch và giọng nói trong cabin thực tế, Vivi còn giữ lại được bao nhiêu phần năng lực?

| Câu hỏi                                                           | Text baseline trả lời được không? | Voice retention trả lời được không? |
| ----------------------------------------------------------------- | --------------------------------: | ----------------------------------: |
| Agent có chọn đúng tool chính thức của Vivi không?                |                                Có |                                  Có |
| Agent có giữ đúng critical slot sau khi đi qua audio không?       |                             Không |                                  Có |
| Tiếng ồn cabin có làm giảm tỷ lệ thành công không?                |                             Không |                                  Có |
| Giọng vùng miền và tốc độ nói có tạo ra chênh lệch đo được không? |                             Không |                                  Có |
| Lỗi đến từ reasoning, schema, hay nghe/nhận dạng audio?           |                          Một phần |        Có, khi so với text baseline |

Nếu không có track này, dự án sẽ bị thu hẹp thành một benchmark text tool-use giá rẻ cộng thêm FDRC. Như vậy sẽ bỏ sót mục tiêu sản phẩm đã nêu: đánh giá khả năng chuyển năng lực từ text sang voice.

Nói dễ hiểu: **Text-to-Voice Capability Retention kiểm tra xem Vivi có bị “tụt năng lực” khi chuyển từ gõ lệnh sang nói lệnh hay không.**

---

## Phân tích kỹ thuật

### Luồng chạy runtime

| Bước                     | Đường dẫn code                                             | Hành vi                                                                                                |
| ------------------------ | ---------------------------------------------------------- | ------------------------------------------------------------------------------------------------------ |
| 1. Load task assets      | `run_voice_retention.py`                                   | Load base tasks và speech overlays, sau đó preflight-validate để kiểm tra asset có nhất quán không     |
| 2. Chọn overlays         | `select_overlays(..., "text_to_voice_retention", domains)` | Lọc các retention overlays theo domain được chọn                                                       |
| 3. Build adapter         | `full_duplex_orchestrator.build_adapter()`                 | Dùng provider adapter như `openai_realtime` cho các lượt chạy audio                                    |
| 4. Build prompt và tools | `build_system_prompt()`, `get_openai_tool_schemas()`       | Cung cấp tool Vivi chính thức theo từng domain và instruction của task                                 |
| 5. Sinh hoặc load audio  | `AudioCache.get_or_build()`                                | Sinh utterance tiếng Việt và cache các biến thể clean/cabin                                            |
| 6. Stream audio          | `_stream_audio()`                                          | Gửi từng chunk audio PCM16 24 kHz vào realtime adapter                                                 |
| 7. Thực thi tool calls   | `_drain_adapter_events()` và `MockToolServer`              | Validate và thực thi tool call của model trên mock state deterministic                                 |
| 8. Tạo episode log       | `run_agent_episode()`                                      | Ghi transcript, normalized events, voice events, tool calls, validation errors, final state và latency |
| 9. Đánh giá              | `evaluate_retention_episode()`                             | Chấm điểm trajectory chính xác, arguments, final state, communication, critical slots và phân loại lỗi |

Hiểu đơn giản, benchmark chạy cùng một task theo nhiều dạng đầu vào:

1. Text baseline.
2. Voice sạch.
3. Voice có nhiễu cabin.

Sau đó so sánh xem cùng một ý định, khi chuyển sang voice, Vivi còn làm đúng được bao nhiêu so với text.

---

## Bề mặt đánh giá

| Lớp đánh giá     | Ý nghĩa                                                                                                                                           |
| ---------------- | ------------------------------------------------------------------------------------------------------------------------------------------------- |
| Tool trajectory  | Model phải gọi đúng chuỗi tool chính thức của Vivi                                                                                                |
| Tool arguments   | Tham số truyền vào tool phải đúng slot kỳ vọng và đúng ràng buộc schema                                                                           |
| Final state      | Trạng thái cuối của mock vehicle/navigation/media phải khớp expected final state                                                                  |
| Critical slots   | Các giá trị quan trọng như nhiệt độ, vị trí, tuyến đường, media target, hoặc contact phải được giữ đúng                                           |
| Communication    | Assistant phải nói đủ thông tin cần thiết cho người dùng nếu task yêu cầu                                                                         |
| Voice condition  | `clean_voice` và `realistic_cabin_voice` được chấm riêng                                                                                          |
| Persona          | Có thể so sánh theo giọng vùng miền và tốc độ nói nếu chạy đủ ma trận persona                                                                     |
| Failure taxonomy | Lỗi được phân loại thành `CRITICAL_SLOT_ERROR`, `VALIDATION_ERROR`, `TOOL_ARGUMENT_ERROR`, `TOOL_SELECTION_ERROR` và các nhóm lỗi dùng chung khác |

Trong đó, **critical slot** là phần đặc biệt quan trọng. Đây là các thông tin nếu nghe sai sẽ làm hành động sai, ví dụ:

* Người dùng nói “22 độ” nhưng hệ thống hiểu thành “24 độ”.
* Người dùng nói “ghế lái” nhưng hệ thống hiểu thành “ghế phụ”.
* Người dùng nói “mở cửa sổ sau bên trái” nhưng hệ thống mở cửa khác.
* Người dùng nói “gọi cho mẹ” nhưng hệ thống chọn sai contact.
* Người dùng nói điểm đến A nhưng hệ thống điều hướng đến điểm B.

---

## Các metric chính

| Metric                       | Định nghĩa                                                   |
| ---------------------------- | ------------------------------------------------------------ |
| `text_pass_at_1`             | Tỷ lệ pass của các episode text baseline                     |
| `clean_voice_pass_at_1`      | Tỷ lệ pass của các episode giọng nói sạch                    |
| `cabin_voice_pass_at_1`      | Tỷ lệ pass của các episode giọng nói có nhiễu cabin          |
| `clean_voice_retention`      | `clean_voice_pass_at_1 / text_pass_at_1`                     |
| `voice_capability_retention` | `cabin_voice_pass_at_1 / text_pass_at_1`                     |
| `voice_degradation_gap`      | `text_pass_at_1 - cabin_voice_pass_at_1`                     |
| `critical_slot_accuracy`     | Tỷ lệ critical slot được giữ đúng                            |
| `accent_gap`                 | Chênh lệch kết quả giữa các vùng giọng khi chạy nhiều accent |
| `speed_gap`                  | Chênh lệch kết quả giữa các tốc độ nói khi chạy nhiều tốc độ |

Metric quan trọng nhất không chỉ là raw voice pass rate. Chỉ nhìn voice pass rate thì chưa đủ, vì có thể task vốn đã khó ngay cả với text.

Do đó, metric chẩn đoán tốt hơn là **retention ratio**, tức là tỷ lệ giữ năng lực so với text baseline trên cùng bề mặt task.

Ví dụ dễ hiểu:

```text id="c7eqjq"
text_pass_at_1 = 0.90
cabin_voice_pass_at_1 = 0.60

voice_capability_retention = 0.60 / 0.90 = 0.67
```

Điều này nghĩa là khi chuyển từ text sang voice cabin, hệ thống chỉ giữ được khoảng 67% năng lực so với baseline text.

---

## Trạng thái hiện tại

Deterministic reference-agent hiện đã pass track này. Điều đó xác nhận rằng:

* Task assets hợp lệ.
* Runner hoạt động đúng.
* Evaluator nhất quán nội bộ.
* Expected trajectory, expected arguments và expected final state được định nghĩa đúng.

Các lần chạy OpenAI realtime surrogate có ích như smoke test, nhưng không nên báo cáo như hiệu năng production của Vivi. Lý do là chúng đo một stack audio/model/provider cụ thể, không phải log thật từ Vivi production.

Trong lần smoke run mới nhất, voice retention trên domain automotive với `gpt-realtime-mini`, persona `vi_north_normal`, gồm cả clean audio và cabin audio, cho điểm thấp.

Failure mode chính là **mất critical slot**. Điều này cho thấy benchmark đang phơi ra được loại suy giảm do audio ingress, tức là lỗi phát sinh khi ý định đi qua đường voice/audio, điều mà text baseline không thể đo được.

---

## Khuyến nghị chiến lược

Nên giữ track này trong MVP.

Lý do: track này là bằng chứng trực tiếp cho claim của dự án rằng năng lực của Vivi được giữ lại khi chuyển từ text sang voice.

Triển khai nên giữ gọn, không overengineering:

1. Giữ ba tầng so sánh chính: `text_baseline`, `clean_voice`, và `realistic_cabin_voice`.
2. Chỉ dùng `gpt-4o-mini` cho text baseline chi phí thấp.
3. Chỉ dùng realtime/audio adapter cho các lượt chạy voice.
4. Bổ sung báo cáo transcript ASR rõ ràng từ `user_transcript_done`, để phân biệt lỗi do nghe/audio, lỗi reasoning/tool, và lỗi policy/schema.
5. Không mở rộng metric quá nhiều khi chưa có log audio thật từ Vivi. Bộ evaluator hiện tại dựa trên exact tool, state và slot đã là tiêu chí pass đúng ở cấp sản phẩm.

---

## Cách hiểu ngắn gọn

Text-to-Voice Capability Retention trả lời câu hỏi:

> Cùng một tác vụ Vivi đã làm được bằng text, khi người dùng nói bằng tiếng Việt thì Vivi còn làm đúng được bao nhiêu?

Track này cần thiết vì benchmark text không thể phát hiện các lỗi đặc thù của voice, như nghe sai số, sai vị trí, sai điểm đến, sai contact, hoặc bị nhiễu cabin làm mất slot quan trọng.

Nói ngắn gọn:

> Đây là benchmark đo độ “rơi rớt năng lực” khi chuyển từ nhập lệnh bằng chữ sang nhập lệnh bằng giọng nói tiếng Việt trong xe.
