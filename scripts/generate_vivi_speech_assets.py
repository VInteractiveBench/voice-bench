"""Generate the deterministic MVP data assets for Vivi-τVoice-CarBench-VN."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SPEECH = ROOT / "src"


def dump_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def dump_jsonl(path: Path, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def call(tool: str, **args) -> dict:
    return {"tool": tool, "args": args}


def task(task_id: str, domain: str, utterance: str, slots: dict, calls: list[dict]) -> dict:
    return {
        "id": task_id,
        "domain": domain,
        "user_goal": utterance,
        "initial_state": {"committed_intent": None},
        "expected_tool_calls": calls,
        "expected_final_state": {"committed_intent": task_id},
        "expected_critical_slots": slots,
        "required_communication": True,
    }


RETENTION = [
    task("base_020_climate_vague_cool", "automotive", "Hey VinFast, đặt điều hòa ghế lái 22 độ.", {"temperature": "22", "position": "driver"}, [call("climate_control", device="temp", value="22", position="driver")]),
    task("base_015_defrost_drive", "automotive", "Bật sấy kính.", {"device": "defrost"}, [call("climate_control", device="defrost", value="true")]),
    task("base_016_eco_drive_confirm", "automotive", "Chuyển chế độ lái eco.", {"drive_mode": "eco"}, [call("drive_system", device="drive_mode", value="eco")]),
    task("base_022_body_mirror_parked", "automotive", "Gập gương.", {"device": "mirror"}, [call("body_control", device="mirror", value="true")]),
    task("base_023_audio_mute_all", "automotive", "Tắt toàn bộ âm thanh.", {"audio_source": "all"}, [call("audio_control", device="all", action="mute")]),
    task("base_024_drive_sport_confirm", "automotive", "Chuyển chế độ lái sport.", {"drive_mode": "sport"}, [call("drive_system", device="drive_mode", value="sport")]),
    task("base_025_comfort_perfume", "automotive", "Bật nước hoa mùi ocean.", {"scent": "ocean"}, [call("comfort_control", device="perfume_diffuser", value="ocean")]),
    task("disambiguation_001_warm_seat", "automotive", "Bật sưởi ghế lái mức 2.", {"level": "2", "position": "driver"}, [call("seat_control", device="seat_heat", value="2", position="driver")]),
    task("disambiguation_009_sunroof_percent", "automotive", "Mở cửa sổ trời 50 phần trăm.", {"window_percent": "50"}, [call("body_control", device="sunroof", value="50")]),
    task("disambiguation_012_fog_front_rear", "automotive", "Bật đèn sương mù phía sau.", {"position": "rear"}, [call("light_control", device="fog_light", value="true", position="rear")]),
    task("navigation_base_001", "navigation", "Chỉ đường tới Vinmec Times City.", {"poi_name": "Vinmec Times City"}, [call("compute_routes", dest_lat=20.997, dest_lng=105.868, dest_name="Vinmec Times City")]),
    task("navigation_base_002", "navigation", "Chỉ đường tới Vincom Times City.", {"poi_name": "Vincom Times City"}, [call("compute_routes", dest_lat=20.994, dest_lng=105.868, dest_name="Vincom Times City")]),
    task("navigation_base_003", "navigation", "Tìm trạm sạc gần đây.", {"category": "charging_station"}, [call("search_places", query="trạm sạc", category="charging_station", max_results=5)]),
    task("navigation_base_004", "navigation", "Tìm bệnh viện ở Quận 1.", {"category": "hospital", "location_query": "Quận 1, TP. HCM"}, [call("search_places", query="bệnh viện", category="hospital", location_query="Quận 1, TP. HCM")]),
    task("navigation_base_005", "navigation", "Kiểm tra giao thông đường Nguyễn Trãi.", {"location_query": "đường Nguyễn Trãi"}, [call("check_traffic", location_query="đường Nguyễn Trãi")]),
    task("navigation_base_006", "navigation", "Hiển thị bản đồ 3D.", {"view": "3d"}, [call("map_control", action="set_view", view="3d")]),
    task("navigation_base_007", "navigation", "Đổi bản đồ sang giao diện vệ tinh.", {"theme": "satellite"}, [call("map_control", action="set_theme", theme="satellite")]),
    task("navigation_base_008", "navigation", "Tính tuyến nhanh tới sân bay Nội Bài.", {"poi_name": "Sân bay Nội Bài", "routing_mode": "fast"}, [call("compute_routes", dest_lat=21.214, dest_lng=105.807, dest_name="Sân bay Nội Bài", routing_mode="fast")]),
    task("navigation_base_009", "navigation", "Lưu địa điểm này là cơ quan.", {"label": "work"}, [call("saved_places", action="save", label="work", lat=21.028, lng=105.854, title="Cơ quan")]),
    task("navigation_base_010", "navigation", "Dừng dẫn đường.", {"navigation_action": "stop_navigation"}, [call("map_control", action="stop_navigation")]),
    task("media_phone_base_001", "media_phone", "Phát nhạc Mỹ Tâm.", {"artist_name": "Mỹ Tâm"}, [call("media_control", command="play", target="Mỹ Tâm", media_type="music")]),
    task("media_phone_base_002", "media_phone", "Tìm bài Chúng ta của tương lai.", {"song_name": "Chúng ta của tương lai"}, [call("media_control", command="search", target="Chúng ta của tương lai", media_type="music")]),
    task("media_phone_base_003", "media_phone", "Chuyển bài tiếp theo.", {"media_command": "next"}, [call("media_control", command="next")]),
    task("media_phone_base_004", "media_phone", "Mở radio 91.0 FM.", {"radio_frequency": "91.0"}, [call("media_control", command="tune", target="91.0", media_type="radio")]),
    task("media_phone_base_005", "media_phone", "Gọi Nguyễn Hoàng Anh.", {"contact_name": "Nguyễn Hoàng Anh"}, [call("phone_manager", intent="confirm_call", target="Nguyễn Hoàng Anh")]),
    task("media_phone_base_006", "media_phone", "Tìm liên hệ anh Nam.", {"contact_name": "anh Nam"}, [call("phone_manager", intent="search", target="anh Nam")]),
    task("media_phone_base_007", "media_phone", "Xem cuộc gọi nhỡ.", {"history_filter": "missed"}, [call("phone_manager", intent="history", history_filter="missed")]),
    task("media_phone_base_008", "media_phone", "Tìm nhà hàng ở Đà Nẵng.", {"location": "Đà Nẵng"}, [call("lifestyle", query="nhà hàng", category="food", location="Đà Nẵng")]),
    task("media_phone_base_009", "media_phone", "Tìm lịch chiếu phim Mai.", {"movie_name": "Mai"}, [call("movie", query="Mai", intent="showtimes")]),
    task("media_phone_base_010", "media_phone", "Xem tử vi Bảo Bình hôm nay.", {"zodiac_sign": "bao_binh"}, [call("zodiac", sign="bao_binh", topic="daily")]),
]


def fdrc(
    index: int,
    category: str,
    base_task_id: str,
    initial_text: str,
    repair_text: str,
    initial_call: dict,
    final_call: dict | None,
    slots: dict,
) -> dict:
    overlay_id = f"fdrc_{category}_{index:03d}"
    timeline = [
        {"t_ms": 0, "speaker": "user", "event": "user_speech_start", "text": initial_text},
        {"t_ms": 2600, "speaker": "assistant", "event": "assistant_speech_expected_start"},
        {"t_ms": 3300, "speaker": "user", "event": "user_interrupt_start", "overlap": True, "text": repair_text},
        {"t_ms": 4000, "event": "assistant_should_yield_by"},
        {"t_ms": 4300, "event": "tool_commit_allowed_after"},
    ]
    final_intent = "cancel" if final_call is None else final_call["tool"]
    return {
        "speech_overlay_id": overlay_id,
        "base_task_id": base_task_id,
        "domain": next(t["domain"] for t in RETENTION if t["id"] == base_task_id),
        "benchmark_track": "full_duplex_repair_to_commit",
        "mode": "full_duplex_repair_to_commit",
        "accent_region": "north",
        "speech_speed": "normal",
        "audio_condition_id": "interaction_stress",
        "initial_spoken_utterance": initial_text,
        "repair_utterance": repair_text,
        "initial_intent": initial_call,
        "final_intent": final_intent,
        "expected_critical_slots": slots,
        "voice_timeline": timeline,
        "forbidden_tool_calls": [initial_call],
        "expected_tool_calls": [] if final_call is None else [final_call],
        "expected_final_state": {"committed_intent": final_intent},
        "voice_assertions": {"max_yield_latency_ms": 700, "must_suppress_old_intent": True, "must_commit_final_intent_only": True},
    }


def build_fdrc() -> list[dict]:
    rows = []
    nav = [
        ("Vincom Times City", "Vinmec Times City", 20.994, 105.868, 20.997, 105.868),
        ("Bến xe Mỹ Đình", "Sân bay Nội Bài", 21.028, 105.778, 21.214, 105.807),
        ("Hồ Gươm", "Lăng Bác", 21.029, 105.852, 21.037, 105.835),
        ("Vincom Bà Triệu", "Vincom Nguyễn Chí Thanh", 21.011, 105.849, 21.023, 105.810),
        ("Ga Hà Nội", "Ga Cát Linh", 21.024, 105.841, 21.028, 105.826),
        ("Bệnh viện Bạch Mai", "Bệnh viện Việt Đức", 21.000, 105.842, 21.028, 105.846),
        ("Công viên Thống Nhất", "Công viên Yên Sở", 21.012, 105.843, 20.969, 105.870),
        ("Aeon Long Biên", "Aeon Hà Đông", 21.027, 105.899, 20.990, 105.751),
    ]
    for i, (old, new, olat, olng, nlat, nlng) in enumerate(nav, 1):
        rows.append(fdrc(i, "navigation", f"navigation_base_{(i % 10) + 1:03d}", f"Dẫn tôi đến {old}.", f"Không, đến {new} cơ.", call("compute_routes", dest_lat=olat, dest_lng=olng, dest_name=old), call("compute_routes", dest_lat=nlat, dest_lng=nlng, dest_name=new), {"poi_name": new}))
    contacts = [("Nguyễn Hoàng Nam", "Nguyễn Hoàng Anh"), ("anh Nam", "chị Lan"), ("Minh Anh", "Minh Ánh"), ("mẹ", "bố"), ("Hà Anh", "Hải Anh"), ("Tuấn", "Tuấn Anh"), ("chị Mai", "chị My"), ("Hoàng", "Hoàng Anh")]
    for i, (old, new) in enumerate(contacts, 1):
        rows.append(fdrc(i, "phone", "media_phone_base_005", f"Gọi {old}.", f"Không, gọi {new}.", call("phone_manager", intent="confirm_call", target=old), call("phone_manager", intent="confirm_call", target=new), {"contact_name": new}))
    vehicle = [
        ("climate", "Đặt điều hòa 22 độ.", "À không, 24 độ.", call("climate_control", device="temp", value="22"), call("climate_control", device="temp", value="24"), {"temperature": "24"}),
        ("window", "Mở kính ghế lái 50 phần trăm.", "Không, ghế phụ 30 phần trăm.", call("body_control", device="window", value="50", position="driver"), call("body_control", device="window", value="30", position="passenger"), {"window_percent": "30", "position": "passenger"}),
        ("fan", "Đặt quạt mức 6.", "Đổi thành mức 4.", call("climate_control", device="fan", value="6"), call("climate_control", device="fan", value="4"), {"fan_level": "4"}),
        ("seat", "Sưởi ghế lái mức 3.", "Ghế phụ mức 2 thôi.", call("seat_control", device="seat_heat", value="3", position="driver"), call("seat_control", device="seat_heat", value="2", position="passenger"), {"level": "2", "position": "passenger"}),
        ("display", "Đặt màn hình 80 phần trăm.", "Không, 50 phần trăm.", call("display_control", device="brightness", value="80"), call("display_control", device="brightness", value="50"), {"brightness": "50"}),
        ("light", "Bật đèn sương phía trước.", "Không, phía sau.", call("light_control", device="fog_light", value="true", position="front"), call("light_control", device="fog_light", value="true", position="rear"), {"position": "rear"}),
        ("audio", "Đặt âm lượng giải trí 70.", "Giảm còn 40.", call("audio_control", device="entertainment", action="set", level=70), call("audio_control", device="entertainment", action="set", level=40), {"volume": "40"}),
        ("drive", "Chuyển sang sport.", "Không, chuyển eco.", call("drive_system", device="drive_mode", value="sport"), call("drive_system", device="drive_mode", value="eco"), {"drive_mode": "eco"}),
    ]
    for i, (_, initial, repair, old, new, slots) in enumerate(vehicle, 1):
        rows.append(fdrc(i, "vehicle", RETENTION[i - 1]["id"], initial, repair, old, new, slots))
    media = [("Sơn Tùng", "Mỹ Tâm"), ("Đen Vâu", "Hà Anh Tuấn"), ("Vũ", "Ngọt"), ("podcast A", "podcast B")]
    for i, (old, new) in enumerate(media, 1):
        rows.append(fdrc(i, "media", f"media_phone_base_{i:03d}", f"Phát {old}.", f"Không, phát {new}.", call("media_control", command="play", target=old, media_type="music"), call("media_control", command="play", target=new, media_type="music"), {"media_target": new}))
    rows.append(fdrc(1, "cancel", "media_phone_base_005", "Gọi anh Nam.", "Thôi hủy.", call("phone_manager", intent="confirm_call", target="anh Nam"), None, {}))
    rows.append(fdrc(2, "cancel", "navigation_base_010", "Dẫn đến Hồ Gươm.", "Thôi hủy.", call("compute_routes", dest_lat=21.029, dest_lng=105.852, dest_name="Hồ Gươm"), None, {}))
    return rows


def retention_overlays() -> list[dict]:
    accents = ["north", "central", "south"]
    speeds = ["normal", "fast", "slow"]
    rows = []
    for index, base in enumerate(RETENTION, 1):
        rows.append(
            {
                "speech_overlay_id": f"ttv_{base['domain']}_{index:03d}",
                "base_task_id": base["id"],
                "domain": base["domain"],
                "benchmark_track": "text_to_voice_retention",
                "mode": "voice_condition_selected_at_runtime",
                "accent_region": accents[(index - 1) % 3],
                "speech_speed": speeds[(index - 1) % 3],
                "audio_condition_id": "runtime_clean_or_cabin_noise",
                "spoken_utterance": base["user_goal"],
                "expected_critical_slots": base["expected_critical_slots"],
                "voice_assertions": {"must_preserve_critical_slots": True, "must_not_commit_wrong_entity": True},
            }
        )
    return rows


def write_domains() -> None:
    for domain in ("navigation", "media_phone"):
        tasks = [row for row in RETENTION if row["domain"] == domain]
        directory = ROOT / "data" / "domains" / domain
        dump_json(directory / "tasks.json", tasks)
        dump_json(directory / "db.json", {"committed_intent": None, "domain": domain})
        (directory / "policy.md").write_text(
            f"# Vivi {domain} policy\n\nUse only official Vivi tools, validate required arguments, ask when ambiguous, and never claim success before execution.\n",
            encoding="utf-8",
        )


def write_conditions() -> None:
    variants = {
        "north": {"navigation": ["rẽ", "chỉ đường"], "negation": ["không", "không phải"]},
        "central": {"navigation": ["rẽ", "chỉ đường"], "negation": ["không", "không phải"]},
        "south": {"navigation": ["quẹo", "cua", "chỉ đường"], "negation": ["không", "hông", "không phải"]},
    }
    for region, lexical in variants.items():
        for speed in ("slow", "normal", "fast"):
            payload = {
                "persona_id": f"vi_{region}_{speed}",
                "language": "vi",
                "accent_region": region,
                "speech_speed": speed,
                "lexical_variants": {**lexical, "filler": ["ờ", "ừ", "à"], "repair_markers": ["à không", "không phải", "ý là", "thôi"]},
                "speech_notes": [f"Use common {region} Vietnamese wording.", f"Speak at {speed} speed."],
            }
            for directory_name in ("persona", "personas"):
                path = SPEECH / directory_name / f"vi_{region}_{speed}.yaml"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")
    conditions = {
        "clean": {"description": "Clean voice baseline", "noise_sources": [], "snr_db_range": None, "packet_loss_rate": 0.0, "muffling": "none", "barge_in_enabled": False},
        "cabin_noise": {"description": "Normal in-car noise", "noise_sources": ["cabin_ac", "road_noise", "low_volume_music"], "snr_db_range": [12, 25], "packet_loss_rate": 0.0, "muffling": "mild", "barge_in_enabled": False},
        "interaction_stress": {"description": "Cabin noise plus full-duplex interaction", "noise_sources": ["cabin_ac", "road_noise", "low_volume_music"], "snr_db_range": [10, 20], "packet_loss_rate": 0.01, "muffling": "mild", "barge_in_enabled": True, "backchannel_enabled": True},
    }
    for condition_id, payload in conditions.items():
        payload = {"condition_id": condition_id, **payload}
        path = SPEECH / "audio_conditions" / f"{condition_id}.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")


def main() -> None:
    fdrc_rows = build_fdrc()
    dump_json(SPEECH / "base_task_manifest.json", RETENTION)
    dump_jsonl(SPEECH / "speech_task_overlays.jsonl", retention_overlays() + fdrc_rows)
    for row in fdrc_rows:
        dump_json(SPEECH / "full_duplex_timelines" / f"{row['speech_overlay_id']}.json", row["voice_timeline"])
    write_domains()
    write_conditions()


if __name__ == "__main__":
    main()
