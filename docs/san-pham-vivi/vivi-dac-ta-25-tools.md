# Đặc tả chi tiết 25 tools của Vivi

> Đây là danh sách **whitelist** đầy đủ các công cụ Vivi được phép gọi. Tài liệu phục vụ việc
> **ánh xạ (mapping)** và **xác thực (validation)** tham số mà mô hình sinh ra khi gọi hàm.
>
> **Cách đọc bảng tham số:**
> - **Bắt buộc** = tham số phải có thì tool mới chạy được; **Tùy chọn** = có thể bỏ qua.
> - Cột *Giá trị / Ví dụ* liệt kê các giá trị hợp lệ. Nếu không nằm trong danh sách này,
>   tham số sẽ bị coi là không hợp lệ ở bước validation.

## Mục lục

- [Nhóm 1 — Điều khiển vật lý xe](#nhóm-1--điều-khiển-vật-lý-xe-vivi-plugins--vehicle) (`vehicle`)
  1. [climate_control](#1-climate_control) · 2. [seat_control](#2-seat_control) · 3. [body_control](#3-body_control) · 4. [light_control](#4-light_control) · 5. [audio_control](#5-audio_control) · 6. [display_control](#6-display_control) · 7. [connectivity_control](#7-connectivity_control) · 8. [drive_system](#8-drive_system) · 9. [comfort_control](#9-comfort_control)
- [Nhóm 2 — Bản đồ & Dẫn đường](#nhóm-2--bản-đồ--dẫn-đường-vivi-plugins--navigation) (`navigation`)
  10. [search_places](#10-search_places) · 11. [compute_routes](#11-compute_routes) · 12. [map_control](#12-map_control) · 13. [saved_places](#13-saved_places) · 14. [check_traffic](#14-check_traffic)
- [Nhóm 3 — Thông tin & Tra cứu](#nhóm-3--thông-tin--tra-cứu)
  15. [weather](#15-weather) · 16. [news_search](#16-news_search) · 17. [web_search](#17-web_search) · 18. [vinfast_kb](#18-vinfast_kb) · 19. [vehicle_troubleshoot](#19-vehicle_troubleshoot) · 20. [software_release](#20-software_release)
- [Nhóm 4 — Phương tiện & Kết nối](#nhóm-4--phương-tiện--kết-nối)
  21. [media_control](#21-media_control) · 22. [phone_manager](#22-phone_manager) · 23. [lifestyle](#23-lifestyle) · 24. [movie](#24-movie) · 25. [zodiac](#25-zodiac)

---

## Nhóm 1 — Điều khiển vật lý xe (`vivi-plugins / vehicle`)

### 1. `climate_control`
**Mục đích:** Điều khiển điều hòa, sưởi ấm, thông gió, rã đông (defrost) và sưởi vô lăng.

| Tham số | Kiểu | Bắt buộc | Giá trị / Ví dụ |
|---|---|---|---|
| `device` | string | ✅ | `ac`, `temp`, `fan`, `defrost`, `fan_direction`, `recirculation`, `steering_heat` |
| `value` | string | ✅ | `"true"`/`"false"` (bật/tắt), số nhiệt độ `"22"`, mức quạt `"5"`, hoặc hướng gió `"face"`/`"feet"` |
| `position` | string | ⬜ | `driver`, `passenger`, `front`, `rear`, `all` (mặc định `all`) |
| `unit` | string | ⬜ | `C`, `F` (mặc định `C`) |

### 2. `seat_control`
**Mục đích:** Điều khiển làm mát ghế, sưởi ghế và massage ghế.

| Tham số | Kiểu | Bắt buộc | Giá trị / Ví dụ |
|---|---|---|---|
| `device` | string | ✅ | `seat_cool`, `seat_heat`, `massage` |
| `value` | string | ✅ | `"true"`/`"false"`, hoặc mức `"1"`, `"2"`, `"3"` |
| `position` | string | ⬜ | `driver`, `passenger`, `rear_left`, `rear_right`, `all` (mặc định `driver`) |

### 3. `body_control`
**Mục đích:** Điều khiển cửa sổ, cửa sổ trời (sunroof), tấm che nắng, gương, khóa cửa, cốp và nắp cổng sạc.

| Tham số | Kiểu | Bắt buộc | Giá trị / Ví dụ |
|---|---|---|---|
| `device` | string | ✅ | `window`, `sunroof`, `sunroof_shade`, `mirror`, `lock`, `trunk`, `charge_port` |
| `value` | string | ✅ | `"true"`/`"false"` (mở/đóng, khóa/mở khóa), hoặc % mức mở `"50"` |
| `position` | string | ⬜ | `driver`, `passenger`, `rear_left`, `rear_right`, `rear`, `front`, `all` |

### 4. `light_control`
**Mục đích:** Điều khiển đèn viền nội thất (ambient), đèn trần, đèn pha và đèn sương mù.

| Tham số | Kiểu | Bắt buộc | Giá trị / Ví dụ |
|---|---|---|---|
| `device` | string | ✅ | `ambient`, `cabin_light`, `headlight`, `fog_light` |
| `value` | string | ✅ | `"true"`/`"false"`, tên màu `"blue"`/`"red"`, hoặc mức sáng `"80"` |
| `position` | string | ⬜ | `front`, `rear`, `all` |

### 5. `audio_control`
**Mục đích:** Điều khiển âm lượng và tắt tiếng (mute) của các nguồn âm thanh trên xe.
*(Chỉ chỉnh âm lượng — không phát/dừng nhạc; phần đó thuộc [`media_control`](#21-media_control).)*

| Tham số | Kiểu | Bắt buộc | Giá trị / Ví dụ |
|---|---|---|---|
| `device` | string | ✅ | `all`, `entertainment`, `phone_ringing`, `phone_in_call`, `voice_assistant`, `navigation`, `reduce_chime` |
| `action` | string | ✅ | `mute`, `unmute`, `set`, `reset` |
| `level` | integer | ⬜ | Mức âm lượng cụ thể (dùng khi `action = set`) |

### 6. `display_control`
**Mục đích:** Điều chỉnh độ sáng màn hình giải trí trung tâm (HMI).

| Tham số | Kiểu | Bắt buộc | Giá trị / Ví dụ |
|---|---|---|---|
| `device` | string | ✅ | `brightness` |
| `value` | string | ✅ | Giá trị độ sáng cụ thể, vd `"70"` |

### 7. `connectivity_control`
**Mục đích:** Quản lý Wi-Fi, Bluetooth và Wi-Fi hotspot của xe.

| Tham số | Kiểu | Bắt buộc | Giá trị / Ví dụ |
|---|---|---|---|
| `device` | string | ✅ | `wifi`, `bluetooth`, `wifi_hotspot` |
| `value` | string | ✅ | `"true"`/`"false"`, hoặc thông số kết nối / thiết bị cụ thể |

### 8. `drive_system`
**Mục đích:** Cài đặt chế độ vận hành (drive mode), mức phanh tái sinh (regen brake) và thiết lập ADAS.

| Tham số | Kiểu | Bắt buộc | Giá trị / Ví dụ |
|---|---|---|---|
| `device` | string | ✅ | `drive_mode`, `regen_brake`, `adas_settings` |
| `value` | string | ✅ | `"comfort"`/`"sport"`/`"eco"` (cho `drive_mode`), hoặc `"true"`/`"false"` / mức cụ thể |

### 9. `comfort_control`
**Mục đích:** Điều khiển máy khuếch tán nước hoa và chế độ riêng tư (privacy mode).

| Tham số | Kiểu | Bắt buộc | Giá trị / Ví dụ |
|---|---|---|---|
| `device` | string | ✅ | `perfume_diffuser`, `privacy_mode` |
| `value` | string | ✅ | `"true"`/`"false"`, hoặc mùi hương `"ocean"`/`"forest"` |

---

## Nhóm 2 — Bản đồ & Dẫn đường (`vivi-plugins / navigation`)

### 10. `search_places`
**Mục đích:** Tìm địa điểm / điểm quan tâm (POI) quanh xe theo tên, danh mục, khu vực, hoặc dọc theo lộ trình đang chạy.

| Tham số | Kiểu | Bắt buộc | Giá trị / Ví dụ |
|---|---|---|---|
| `query` | string | ✅ | Từ khóa tìm kiếm, vd `"Cây xăng Petrolimex"`, `"Khách sạn Vinpearl"` |
| `category` | string | ⬜ | `gas_station`, `charging_station`, `restaurant`, `parking`, `hospital`, `hotel`, `atm`, `pharmacy`, `cafe` |
| `lat` | number | ⬜ | Vĩ độ trung tâm tìm kiếm |
| `lng` | number | ⬜ | Kinh độ trung tâm tìm kiếm |
| `radius` | number | ⬜ | Bán kính tìm kiếm (mét) |
| `max_results` | integer | ⬜ | Số kết quả tối đa (mặc định `5`) |
| `location_query` | string | ⬜ | Tên thành phố / khu vực, vd `"Quận 1, TP. HCM"` |
| `route_id` | string | ⬜ | ID lộ trình đang chạy (lấy từ [`compute_routes`](#11-compute_routes)) để tìm dọc đường |
| `time_offset` | integer | ⬜ | Mốc thời gian (phút) dọc lộ trình, vd tìm sau 120 phút lái |
| `distance_offset_km` | number | ⬜ | Mốc khoảng cách (km) dọc lộ trình, vd tìm sau `"50"` km |
| `open_now` | boolean | ⬜ | Chỉ lọc địa điểm đang mở cửa |

### 11. `compute_routes`
**Mục đích:** Tính lộ trình từ vị trí hiện tại đến điểm đích (hỗ trợ tuyến thay thế, thông tin lộ trình và điểm dừng trung gian).

| Tham số | Kiểu | Bắt buộc | Giá trị / Ví dụ |
|---|---|---|---|
| `action` | string | ⬜ | `calculate` (xem trước), `alternatives` (tuyến thay thế), `route_info` (thời gian + khoảng cách) |
| `dest_lat` | number | ✅ | Vĩ độ điểm đến |
| `dest_lng` | number | ✅ | Kinh độ điểm đến |
| `dest_name` | string | ⬜ | Tên hiển thị điểm đến |
| `origin_lat` | number | ⬜ | Vĩ độ điểm xuất phát (ghi đè vị trí hiện tại) |
| `origin_lng` | number | ⬜ | Kinh độ điểm xuất phát (ghi đè) |
| `via_waypoints` | array<object> | ⬜ | Điểm dừng trung gian, mỗi object: `{"lat": number, "lng": number, "name": string, "stop_duration_min": integer}` |
| `avoid` | string | ⬜ | Các thứ cần tránh, ngăn cách bởi dấu phẩy, vd `"tollRoad,highway"` |
| `routing_mode` | string | ⬜ | `fast`, `short`, `eco` |
| `num_alternatives` | integer | ⬜ | Số tuyến thay thế để so sánh (mặc định `3`) |

### 12. `map_control`
**Mục đích:** Điều khiển hiển thị bản đồ và trạng thái dẫn đường thực tế *(không tính toán lộ trình)*.

| Tham số | Kiểu | Bắt buộc | Giá trị / Ví dụ |
|---|---|---|---|
| `action` | string | ✅ | `set_view`, `set_theme`, `orientation`, `start_navigation`, `stop_navigation` |
| `view` | string | ⬜ | `"2d"`, `"3d"` (cho `set_view`) |
| `theme` | string | ⬜ | `"default"`, `"satellite"` (cho `set_theme`) |
| `orientation` | string | ⬜ | `"north_up"`, `"heading_up"` (cho `orientation`) |

### 13. `saved_places`
**Mục đích:** Quản lý danh sách địa điểm yêu thích (Nhà riêng, Cơ quan, Yêu thích).

| Tham số | Kiểu | Bắt buộc | Giá trị / Ví dụ |
|---|---|---|---|
| `action` | string | ✅ | `save`, `list` |
| `label` | string | ⬜ | `"home"`, `"work"`, hoặc tên tùy chỉnh |
| `lat` | number | ⬜ | Vĩ độ địa điểm |
| `lng` | number | ⬜ | Kinh độ địa điểm |
| `address` | string | ⬜ | Địa chỉ cụ thể |
| `title` | string | ⬜ | Tiêu đề hiển thị |

### 14. `check_traffic`
**Mục đích:** Kiểm tra mật độ giao thông, mức tắc nghẽn, thời gian trễ và sự cố giao thông lân cận.

| Tham số | Kiểu | Bắt buộc | Giá trị / Ví dụ |
|---|---|---|---|
| `location_query` | string | ⬜ | Tên tuyến đường / khu vực cần kiểm tra |
| `lat` | number | ⬜ | Vĩ độ điểm kiểm tra |
| `lng` | number | ⬜ | Kinh độ điểm kiểm tra |
| `radius` | integer | ⬜ | Bán kính quét (mét, mặc định `2000`) |

---

## Nhóm 3 — Thông tin & Tra cứu
*(`vivi-plugins / weather, news, web-search, vinfast-kb`)*

### 15. `weather`
**Mục đích:** Xem thời tiết hiện tại hoặc dự báo tại một địa điểm.

| Tham số | Kiểu | Bắt buộc | Giá trị / Ví dụ |
|---|---|---|---|
| `location` | string | ⬜ | Tên thành phố / khu vực (mặc định là vị trí hiện tại của xe) |
| `date` | string | ⬜ | `"today"`, `"tomorrow"`, hoặc `"DD/MM/YYYY"` |
| `lat` | number | ⬜ | Vĩ độ |
| `lon` | number | ⬜ | Kinh độ |

### 16. `news_search`
**Mục đích:** Tìm và đọc các bài tin tức mới nhất.

| Tham số | Kiểu | Bắt buộc | Giá trị / Ví dụ |
|---|---|---|---|
| `question` | string | ✅ | Nội dung / từ khóa truy vấn tin tức |
| `category` | string | ⬜ | `thể thao`, `khoa học công nghệ`, `kinh doanh`, `sức khỏe`, `giải trí`, `thời sự`, `pháp luật`, `giáo dục` |

### 17. `web_search`
**Mục đích:** Tìm kiếm thông tin mở rộng trên Internet (qua Perplexity API).

| Tham số | Kiểu | Bắt buộc | Giá trị / Ví dụ |
|---|---|---|---|
| `query` | string | ✅ | Nội dung truy vấn |
| `mode` | string | ⬜ | `news`, `knowledge`, `calendar`, `vingroup` |
| `search_recency_filter` | string | ⬜ | `day`, `week`, `month`, `year` |

### 18. `vinfast_kb`
**Mục đích:** Tra cứu thông số kỹ thuật, tính năng, hướng dẫn sử dụng, chính sách bán hàng & dịch vụ xe VinFast.

| Tham số | Kiểu | Bắt buộc | Giá trị / Ví dụ |
|---|---|---|---|
| `query` | string | ✅ | Câu hỏi tra cứu |
| `car_model` | string | ⬜ | Dòng xe liên quan, vd `"VF8"` |
| `categories` | array<string> | ⬜ | Các danh mục tài liệu muốn lọc |

### 19. `vehicle_troubleshoot`
**Mục đích:** Chẩn đoán lỗi xe, cảnh báo, hành vi bất thường và đưa hướng dẫn chẩn đoán từng bước.

| Tham số | Kiểu | Bắt buộc | Giá trị / Ví dụ |
|---|---|---|---|
| `query` | string | ✅ | Mô tả hiện tượng / lỗi gặp phải |
| `affected_area` | string | ⬜ | `battery`, `tires`, `brakes`, `steering`, `infotainment`, `climate`, `charging`, `body`, `other` |
| `error_code` | string | ⬜ | Mã lỗi cụ thể (vd OBD code) |

### 20. `software_release`
**Mục đích:** Tra cứu phiên bản phần mềm xe, lịch sử cập nhật OTA/FOTA và tính năng mới.

| Tham số | Kiểu | Bắt buộc | Giá trị / Ví dụ |
|---|---|---|---|
| `query` | string | ✅ | Từ khóa tra cứu |
| `version` | string | ⬜ | Số phiên bản cụ thể |
| `check_latest` | boolean | ⬜ | `true` nếu muốn kiểm tra phiên bản mới nhất |

---

## Nhóm 4 — Phương tiện & Kết nối
*(`vivi-plugins / media, phone`)*

### 21. `media_control`
**Mục đích:** Điều khiển trình phát nhạc, radio, podcast và duyệt thư viện media.
*(Không bao gồm tăng/giảm âm lượng — phần đó thuộc [`audio_control`](#5-audio_control).)*

| Tham số | Kiểu | Bắt buộc | Giá trị / Ví dụ |
|---|---|---|---|
| `command` | string | ✅ | `play`, `pause`, `stop`, `next`, `prev`, `seek`, `tune`, `search`, `source`, `shuffle`, `repeat`, `browse`, `list_playlists` |
| `target` | string | ⬜ | Tên bài hát / ca sĩ / playlist, hoặc tần số FM (vd `"91.0"`) |
| `media_type` | string | ⬜ | `music`, `radio`, `podcast`, `audiobook` |
| `value` | integer | ⬜ | Số giây trượt tới/lui (cho `seek`) |

### 22. `phone_manager`
**Mục đích:** Thao tác cuộc gọi, tìm danh bạ, xem lịch sử và quản lý phản ánh dịch vụ.

| Tham số | Kiểu | Bắt buộc | Giá trị / Ví dụ |
|---|---|---|---|
| `intent` | string | ✅ | `call`, `search`, `history`, `complaint`, `confirm_call`, `cancel_call` |
| `target` | string | ⬜ | Tên danh bạ, số điện thoại, hoặc nội dung phản ánh |
| `history_filter` | string | ⬜ | `all`, `missed`, `incoming`, `outgoing` (cho `history`) |

### 23. `lifestyle`
**Mục đích:** Tra cứu thông tin du lịch, ẩm thực / công thức nấu ăn, nhà hàng và văn hóa.

| Tham số | Kiểu | Bắt buộc | Giá trị / Ví dụ |
|---|---|---|---|
| `query` | string | ✅ | Từ khóa cần tra cứu |
| `category` | string | ⬜ | `travel`, `food`, `culture` |
| `location` | string | ⬜ | Vùng / địa điểm cụ thể |

### 24. `movie`
**Mục đích:** Tra cứu lịch chiếu phim, thông tin rạp hoặc đặt vé.

| Tham số | Kiểu | Bắt buộc | Giá trị / Ví dụ |
|---|---|---|---|
| `query` | string | ✅ | Tên phim hoặc nội dung tìm kiếm |
| `intent` | string | ⬜ | `showtimes`, `info`, `booking` |
| `cinema` | string | ⬜ | Tên rạp cụ thể |
| `date` | string | ⬜ | Ngày chiếu mong muốn |

### 25. `zodiac`
**Mục đích:** Xem tử vi cung hoàng đạo (ngày/tuần/tháng), tính cách, độ tương thích.

| Tham số | Kiểu | Bắt buộc | Giá trị / Ví dụ |
|---|---|---|---|
| `sign` | string | ⬜ | Tên chòm sao (tiếng Việt không dấu): `bach_duong`, `kim_nguu`, `song_tu`, `cu_giai`, `su_tu`, `xu_nu`, `thien_binh`, `bo_cap`, `nhan_ma`, `ma_ket`, `bao_binh`, `song_ngu` |
| `topic` | string | ⬜ | `daily`, `weekly`, `monthly`, `personality`, `love`, `career`, `compatibility` |
