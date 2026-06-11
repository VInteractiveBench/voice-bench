# Phân công domain

> Bảng phân công TTS phụ trách từng domain. Cập nhật khi có thay đổi nhân sự / phạm vi.
> Mỗi domain build theo [Hướng dẫn xây dựng domain](huong-dan-xay-dung-domain.md).

## Bản đồ domain → tools

Bốn nhóm tool của Vivi (xem [đặc tả 25 tools](../san-pham-vivi/vivi-dac-ta-25-tools.md))
được đề xuất cắt thành các domain như sau:

| Domain | Plugin nguồn | Tools | Phụ trách (PIC) | Trạng thái |
|---|---|---|---|---|
| **Điều khiển hệ thống xe** | `vehicle` | `climate_control`, `seat_control`, `body_control`, `light_control`, `audio_control`, `display_control`, `connectivity_control`, `drive_system`, `comfort_control` | **Nguyen Quang Tung** | ⬜ Chưa bắt đầu |
| **Bản đồ & Dẫn đường** | `navigation` | `search_places`, `compute_routes`, `map_control`, `saved_places`, `check_traffic` | **Tran Nhat Hoang** | ⬜ Chưa bắt đầu |
| **Thông tin & Tra cứu** | `weather`, `news`, `web-search`, `vinfast-kb` | `weather`, `news_search`, `web_search`, `vinfast_kb`, `vehicle_troubleshoot`, `software_release` | **Dao Van Son** *(1 trong 2 — chờ chốt)* | ⬜ Chưa bắt đầu |
| **Phương tiện & Kết nối** | `media`, `phone` | `media_control`, `phone_manager`, `lifestyle`, `movie`, `zodiac` | **Dao Van Son** *(1 trong 2 — chờ chốt)* | ⬜ Chưa bắt đầu |

> **Ghi chú:** Dao Van Son chọn **1 trong 2** domain *Thông tin & Tra cứu* hoặc *Phương tiện & Kết nối*;
> domain còn lại sẽ phân công sau (chốt trong tuần — xem [meeting note 2026-05-29](../../meeting-notes/2026/2026-05-29-kickoff-gioi-thieu-du-an.md)).

**Chú thích trạng thái:** ⬜ Chưa bắt đầu · 🟡 Đang làm · 🟢 Chờ review · ✅ Hoàn thành.

## Workstream song song: Speech Interaction Benchmark

| Workstream | Mô tả | Phụ trách (PIC) | Trạng thái |
|---|---|---|---|
| **Speech Interaction Benchmark (tiếng Việt)** | Phát triển bộ benchmark đánh giá **tương tác giọng nói** cho Vivi, lấy ý tưởng tương tự **tau-3 bench** nhưng thích ứng cho **tiếng Việt**. | **Luong Thanh Hau** | ⬜ Chưa bắt đầu |

## Tiến độ chi tiết theo domain

> Mỗi người tự cập nhật checklist domain của mình.

### Điều khiển hệ thống xe — _Nguyen Quang Tung_
- [ ] `policy.md`
- [ ] `db.json`
- [ ] `tools.py`
- [ ] `tasks.json` (base / hallucination / disambiguation)
- [ ] Self-check + review

### Bản đồ & Dẫn đường — _Tran Nhat Hoang_
- [ ] `policy.md`
- [ ] `db.json`
- [ ] `tools.py`
- [ ] `tasks.json` (base / hallucination / disambiguation)
- [ ] Self-check + review

### Thông tin & Tra cứu — _Dao Van Son (1 trong 2)_
- [ ] `policy.md`
- [ ] `db.json`
- [ ] `tools.py`
- [ ] `tasks.json` (base / hallucination / disambiguation)
- [ ] Self-check + review

### Phương tiện & Kết nối — _Dao Van Son (1 trong 2)_
- [ ] `policy.md`
- [ ] `db.json`
- [ ] `tools.py`
- [ ] `tasks.json` (base / hallucination / disambiguation)
- [ ] Self-check + review

### Speech Interaction Benchmark (tiếng Việt) — _Luong Thanh Hau_
- [ ] Nghiên cứu tau-3 bench & cách đánh giá tương tác giọng nói
- [ ] Đề xuất phạm vi & phương pháp cho tiếng Việt
- [ ] Phác thảo pipeline / bộ task speech
- [ ] Self-check + review
