# Hướng dẫn xây dựng một domain

> Dành cho TTS phụ trách build domain. Trước khi đọc, hãy nắm
> [Tổng quan benchmark](tong-quan-benchmark.md) và xem
> [đặc tả 25 tools](../san-pham-vivi/vivi-dac-ta-25-tools.md).

Một **domain** là một lát cắt chức năng của Vivi (vd: *Điều khiển hệ thống xe*) được mô tả
đầy đủ để chạy đánh giá tự động. Mục tiêu của bạn: tạo ra 4 thành phần `policy` + `database`
+ `tools` + `tasks` cho domain mình phụ trách.

## Bố cục thư mục một domain (gợi ý)

```
domains/<ten_domain>/
├── policy.md        # Quy tắc & ràng buộc của domain
├── db.json          # Dữ liệu / trạng thái mô phỏng ban đầu
├── tools.py         # Định nghĩa các tool (hàm) của domain
└── tasks.json       # Tập kịch bản đánh giá
```
*(Quy ước file cuối cùng theo repo code sẽ chốt sau; tài liệu này tập trung vào **nội dung** cần chuẩn bị.)*

## Các bước thực hiện

### Bước 1 — Chọn phạm vi & tool của domain
- Xác định domain bạn phụ trách (xem [phan-cong-domain.md](phan-cong-domain.md)).
- Liệt kê các tool thuộc domain từ [đặc tả 25 tools](../san-pham-vivi/vivi-dac-ta-25-tools.md).
  Ví dụ domain *Điều khiển hệ thống xe* gồm `climate_control`, `seat_control`, `body_control`,
  `light_control`, `audio_control`, `display_control`, `connectivity_control`, `drive_system`, `comfort_control`.

### Bước 2 — Viết `policy.md`
Mô tả rõ ràng những quy tắc agent **phải** tuân theo. Tập trung vào tình huống dễ sai:
- **Xác nhận trước khi hành động nhạy cảm** (vd: gọi điện, mở khóa, mở cốp).
- **Ràng buộc an toàn** (vd: không hạ kính/mở cửa sổ trời khi đang chạy tốc độ cao — nếu áp dụng).
- **Giới hạn giá trị hợp lệ** (vd: nhiệt độ, mức quạt, % mở).
- **Khi nào phải hỏi lại** thay vì đoán; **khi nào phải từ chối**.

### Bước 3 — Dựng `db.json` (môi trường)
Mô tả trạng thái ban đầu của thế giới mà tool sẽ đọc/ghi. Ví dụ với domain xe:
- Trạng thái điều hòa (đang bật/tắt, nhiệt độ hiện tại), trạng thái cửa/khóa, đèn…
- Với navigation: danh sách POI, địa điểm đã lưu, tuyến đường mẫu.

Database giúp tool trả kết quả nhất quán và để evaluator kiểm tra trạng thái sau hành động.

### Bước 4 — Định nghĩa `tools.py`
Mỗi tool là một hàm:
- **Input** đúng theo bảng tham số trong đặc tả (tên, kiểu, bắt buộc/tùy chọn, giá trị hợp lệ).
- **Validation** tham số đầu vào (đúng kiểu, đúng enum) → trả lỗi rõ ràng nếu sai.
- **Tác động** lên `db.json` (nếu là hành động) và **trả kết quả** có cấu trúc.

### Bước 5 — Viết `tasks.json`
Mỗi task là một kịch bản đánh giá. Xây cả **3 loại** task (theo car-bench):

| Loại | Mục đích | Ví dụ |
|---|---|---|
| **Base** | Tác vụ thực hiện được bình thường | "Bật điều hòa 22 độ ghế lái" |
| **Hallucination** | Yêu cầu *không thể* làm — kiểm tra agent có từ chối/không bịa | "Mở cửa sổ trời" trên xe **không có** cửa sổ trời |
| **Disambiguation** | Yêu cầu *mơ hồ* — kiểm tra agent có hỏi lại | "Chỉnh ghế cho ấm hơn" (chưa rõ ghế nào, mức mấy) |

Mỗi task nên có tối thiểu:
```jsonc
{
  "id": "vehicle_base_001",
  "type": "base",                       // base | hallucination | disambiguation
  "user_goal": "Bật điều hòa 22 độ phía ghế lái",
  "initial_state": { /* override db.json nếu cần */ },
  "evaluation_criteria": {
    "actions": [                        // chuỗi tool call kỳ vọng
      { "tool": "climate_control",
        "args": { "device": "ac", "value": "true", "position": "driver" } },
      { "tool": "climate_control",
        "args": { "device": "temp", "value": "22", "position": "driver" } }
    ],
    "reward_basis": ["actions"]         // tiêu chí dùng để tính điểm
  }
}
```
> Lưu ý: schema trên là **mô tả khái niệm** để thống nhất cách nghĩ. Schema JSON chính thức
> sẽ chốt cùng repo code; khi đó tài liệu này được cập nhật.

### Bước 6 — Tự kiểm tra (self-check)
- [ ] Mọi tool trong tasks đều có trong `tools.py` và khớp đặc tả tham số.
- [ ] Mỗi task chạy được tới trạng thái kết thúc; `evaluation_criteria` khớp với hành vi đúng.
- [ ] Có đủ cả 3 loại task (base / hallucination / disambiguation).
- [ ] Policy bao phủ các tình huống nhạy cảm của domain.
- [ ] Đặt tên, mô tả bằng tiếng Việt rõ ràng; dữ liệu sát bối cảnh Việt Nam.

## Định nghĩa "hoàn thành" (Definition of Done)
Một domain coi là xong khi: đủ 4 thành phần, có ≥ N task mỗi loại (số lượng chốt khi họp),
chạy thử qua được pipeline đánh giá, và được review trong buổi họp tuần.

➡️ Xem phân công cụ thể tại [phan-cong-domain.md](phan-cong-domain.md).
