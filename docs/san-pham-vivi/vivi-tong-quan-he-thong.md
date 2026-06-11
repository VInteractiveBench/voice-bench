# Tổng quan hệ thống Vivi

> **Tài liệu tham khảo về sản phẩm.** Giải thích Vivi hoạt động ở mức tổng quan, trước khi
> bạn đi sâu vào [đặc tả từng tool](vivi-dac-ta-25-tools.md). Đây là nền tảng để cắt thành các
> domain của benchmark — xem [Tổng quan VInteractiveBench](../benchmark/tong-quan-benchmark.md).

## 1. Vivi giải quyết bài toán gì?

Người dùng trên xe VinFast nói chuyện với Vivi bằng **ngôn ngữ tự nhiên** ("Bật điều hòa
22 độ", "Tìm trạm sạc gần đây", "Thời tiết Hà Nội ngày mai thế nào?"). Vivi cần:

1. **Hiểu** người dùng muốn gì.
2. **Chọn đúng công cụ (tool)** để thực hiện.
3. **Điền đúng tham số** cho công cụ đó.
4. **Thực thi** và phản hồi lại người dùng.

## 2. Luồng hoạt động cơ bản

```
Người dùng nói
      │
      ▼
[ ASR ] ──► chuyển giọng nói thành văn bản
      │
      ▼
[ LLM ] ──► hiểu ý định + chọn tool + sinh tham số (function call)
      │
      ▼
[ Lớp validation ] ──► kiểm tra tool có nằm trong whitelist không,
      │                 tham số có hợp lệ không
      ▼
[ Tool / Plugin ] ──► thực thi (điều khiển xe, gọi API bản đồ, tra cứu...)
      │
      ▼
[ LLM ] ──► tổng hợp kết quả thành câu trả lời tự nhiên
      │
      ▼
[ TTS ] ──► đọc phản hồi cho người dùng
```

## 3. Khái niệm "tool" và "whitelist"

- **Tool** là một hàm có khả năng cụ thể (vd: `climate_control` để chỉnh điều hòa). Mỗi tool
  có một bộ **tham số** xác định (tên, kiểu dữ liệu, bắt buộc/tùy chọn, giá trị cho phép).
- **Whitelist 25 tools** là danh sách *đầy đủ và duy nhất* những việc Vivi được phép làm.
  Mô hình không được "bịa" ra tool ngoài danh sách này.
- Khi LLM gọi một tool, hệ thống thực hiện hai bước quan trọng:
  - **Mapping (ánh xạ):** khớp ý định người dùng → tool + tham số.
  - **Validation (xác thực):** đảm bảo tham số đúng kiểu, đúng giá trị cho phép trước khi
    thực thi. Đây là lý do mỗi tool trong đặc tả ghi rõ kiểu dữ liệu và danh sách giá trị hợp lệ.

## 4. Các nhóm tool (plugin)

25 tools được tổ chức trong `vivi-plugins`, chia thành 4 nhóm theo chức năng:

| Nhóm | Plugin | Mục đích | Số tool |
|---|---|---|---|
| 1. Điều khiển vật lý xe | `vehicle` | Điều hòa, ghế, cửa, đèn, âm thanh, lái... | 9 (tool 1–9) |
| 2. Bản đồ & Dẫn đường | `navigation` | Tìm địa điểm, tính lộ trình, giao thông | 5 (tool 10–14) |
| 3. Thông tin & Tra cứu | `weather`, `news`, `web-search`, `vinfast-kb` | Thời tiết, tin tức, tra cứu xe VinFast | 6 (tool 15–20) |
| 4. Phương tiện & Kết nối | `media`, `phone` | Nhạc/đài, điện thoại, giải trí, đời sống | 5 (tool 21–25) |

👉 Chi tiết từng tool: [Đặc tả 25 tools](vivi-dac-ta-25-tools.md).
