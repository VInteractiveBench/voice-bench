# Tổng quan VInteractiveBench

> Tài liệu này giải thích **chúng ta đang xây dựng benchmark gì, vì sao, và học gì từ
> τ²-bench + car-bench**. Đọc xong tài liệu này trước khi sang
> [Hướng dẫn xây dựng domain](huong-dan-xay-dung-domain.md).

## 1. Mục tiêu

**VInteractiveBench** đo độ tin cậy của trợ lý ảo **Vivi** khi xử lý yêu cầu người dùng
bằng ngôn ngữ tự nhiên qua **nhiều lượt hội thoại**. Một lượt đánh giá kiểm tra Vivi có:

1. **Hiểu đúng** ý định người dùng;
2. **Chọn đúng tool** trong danh sách whitelist;
3. **Điền đúng tham số** cho tool;
4. **Hoàn thành tác vụ** đúng kết quả mong đợi;
5. **Tuân thủ policy** (an toàn, quyền hạn, xác nhận trước khi thực hiện hành động nhạy cảm);
6. **Biết giới hạn của mình** — hỏi lại khi mơ hồ, từ chối khi không làm được, thay vì "bịa".

Khác với benchmark hỏi-đáp một lượt, đây là benchmark **tương tác (interactive)**: có một
**user simulator** đóng vai người dùng, hội thoại diễn ra qua lại cho tới khi tác vụ hoàn tất
hoặc thất bại.

## 2. Học gì từ hai benchmark nguồn

### τ²-bench (Sierra Research)
Khung mô phỏng agent chăm sóc khách hàng, đa domain (airline, retail, telecom…). Các ý tưởng ta tái sử dụng:

- **Cấu trúc một domain** = `policy` + `database` + `tools` + `tasks`.
- **User simulator:** mô hình đóng vai người dùng theo kịch bản và ràng buộc của task.
- **Dual-control:** cả agent lẫn user simulator đều có "quyền hành động", tạo hội thoại thực tế.
- **Chấm điểm theo `evaluation_criteria`:** so sánh chuỗi hành động/tool agent thực hiện với
  đáp án kỳ vọng; `reward_basis` quyết định tiêu chí nào tính điểm.

### car-bench
Benchmark cho trợ lý **trong xe** — đúng bối cảnh Vivi. Các ý tưởng ta tái sử dụng:

- **Bối cảnh ô tô:** nhiều tool liên kết nhau (navigation, vehicle control, charging…), kèm
  dữ liệu mô phỏng (POI, tuyến đường, thời tiết, danh bạ, lịch).
- **Đo "epistemic reliability":** agent có biết *khi nào được hành động, khi nào cần hỏi thêm,
  khi nào nên từ chối*.
- **Ba loại task:**
  - **Base** — multi-turn tool use bình thường, tuân thủ policy.
  - **Hallucination** — yêu cầu *không thể thực hiện được*, để xem agent có "bịa" hay không.
  - **Disambiguation** — yêu cầu *mơ hồ*, agent phải hỏi lại để làm rõ.
- **Chỉ số đánh giá:**
  - **Pass@k** — *năng lực tiềm năng*: ít nhất 1/k lần chạy thành công.
  - **Pass^k** — *độ ổn định*: **tất cả** k lần chạy đều thành công.

## 3. Một domain gồm những gì?

Mỗi domain của Vivi (mỗi TTS phụ trách) được mô tả bằng 4 thành phần, theo mô hình τ²-bench:

| Thành phần | File (gợi ý) | Nội dung |
|---|---|---|
| **Policy** | `policy.md` | Quy tắc & ràng buộc agent phải tuân theo trong domain (vd: phải xác nhận trước khi gọi điện, không mở cốp khi xe đang chạy…). |
| **Database / Environment** | `db.json` | Dữ liệu mô phỏng trạng thái thế giới (vd: trạng thái điều hòa hiện tại, danh bạ, danh sách địa điểm…). |
| **Tools** | `tools.py` | Các hàm agent được phép gọi trong domain — lấy từ [đặc tả 25 tools](../san-pham-vivi/vivi-dac-ta-25-tools.md). |
| **Tasks** | `tasks.json` | Tập kịch bản đánh giá: yêu cầu người dùng, trạng thái ban đầu, `evaluation_criteria` (chuỗi hành động/kết quả kỳ vọng). |

## 4. Luồng một lượt đánh giá

```
        ┌──────────────────────────────┐
        │  Task (kịch bản + đáp án kỳ   │
        │  vọng + trạng thái ban đầu)   │
        └──────────────┬───────────────┘
                       ▼
  ┌─────────────┐  hội thoại  ┌──────────────────┐
  │ User        │ ◄────────► │  Vivi Agent      │
  │ Simulator   │   nhiều     │  (model + tools) │
  │ (đóng vai   │   lượt      └────────┬─────────┘
  │  người dùng)│                      │ gọi tool
  └─────────────┘                      ▼
                              ┌──────────────────┐
                              │ Domain env + DB  │
                              └────────┬─────────┘
                                       ▼
                              ┌──────────────────┐
                              │ Evaluator        │
                              │ so khớp hành động│
                              │ với đáp án → điểm│
                              └──────────────────┘
```

## 5. Liên hệ với sản phẩm Vivi

Vivi có sẵn **25 tools** chia 4 nhóm chức năng — chính là nền tảng để cắt thành các domain
của benchmark. Xem:

- [Tổng quan hệ thống Vivi](../san-pham-vivi/vivi-tong-quan-he-thong.md)
- [Đặc tả 25 tools](../san-pham-vivi/vivi-dac-ta-25-tools.md)

➡️ Tiếp theo: [Hướng dẫn xây dựng một domain](huong-dan-xay-dung-domain.md).
