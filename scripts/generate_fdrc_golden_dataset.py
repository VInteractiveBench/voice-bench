"""Generate the balanced Full-Duplex Repair-to-Commit golden dataset."""

from __future__ import annotations

from generate_vivi_speech_assets import SPEECH, call, dump_jsonl, fdrc


def golden_fdrc(
    *,
    domain: str,
    accent: str,
    repair_mode: str,
    index: int,
    base_task_id: str,
    initial_text: str,
    repair_text: str,
    initial_call: dict,
    final_call: dict | None,
    slots: dict,
) -> dict:
    row = fdrc(
        index,
        f"golden_{domain}_{accent}_{repair_mode}",
        base_task_id,
        initial_text,
        repair_text,
        initial_call,
        final_call,
        slots,
    )
    row["speech_overlay_id"] = f"fdrc_golden_{domain}_{accent}_{repair_mode}"
    row["accent_region"] = accent
    row["golden_dataset_id"] = "fdrc_balanced_v1"
    row["repair_mode"] = repair_mode
    row["coverage_axes"] = {
        "domain": domain,
        "accent_region": accent,
        "repair_mode": repair_mode,
    }
    return row


def build_golden_fdrc() -> list[dict]:
    """Balanced FDRC golden set: 3 domains x 3 accents x 3 repair modes."""
    rows = []
    accents = ["north", "central", "south"]
    mode_specs = {
        "entity_repair": {
            "automotive": (
                "base_016_eco_drive_confirm",
                "Chuyển sang sport.",
                {
                    "north": "Không, chuyển eco.",
                    "central": "À không, chuyển eco.",
                    "south": "Hông, chuyển eco.",
                },
                call("drive_system", device="drive_mode", value="sport"),
                call("drive_system", device="drive_mode", value="eco"),
                {"drive_mode": "eco"},
            ),
            "navigation": (
                "navigation_base_001",
                "Dẫn tôi đến Vincom Times City.",
                {
                    "north": "Không, đến Vinmec Times City.",
                    "central": "À không, đến Vinmec Times City.",
                    "south": "Hông, tới Vinmec Times City.",
                },
                call("compute_routes", dest_lat=20.994, dest_lng=105.868, dest_name="Vincom Times City"),
                call("compute_routes", dest_lat=20.997, dest_lng=105.868, dest_name="Vinmec Times City"),
                {"poi_name": "Vinmec Times City"},
            ),
            "media_phone": (
                "media_phone_base_001",
                "Phát Sơn Tùng.",
                {
                    "north": "Không, phát Mỹ Tâm.",
                    "central": "À không, phát Mỹ Tâm.",
                    "south": "Hông, phát Mỹ Tâm.",
                },
                call("media_control", command="play", target="Sơn Tùng", media_type="music"),
                call("media_control", command="play", target="Mỹ Tâm", media_type="music"),
                {"media_target": "Mỹ Tâm"},
            ),
        },
        "slot_repair": {
            "automotive": (
                "base_020_climate_vague_cool",
                "Đặt điều hòa 22 độ.",
                {
                    "north": "Không, 24 độ.",
                    "central": "À không, 24 độ.",
                    "south": "Hông, 24 độ.",
                },
                call("climate_control", device="temp", value="22"),
                call("climate_control", device="temp", value="24"),
                {"temperature": "24"},
            ),
            "navigation": (
                "navigation_base_008",
                "Tính tuyến nhanh tới sân bay Nội Bài.",
                {
                    "north": "Không, chọn tuyến tiết kiệm.",
                    "central": "À không, chọn tuyến tiết kiệm.",
                    "south": "Hông, chọn tuyến tiết kiệm.",
                },
                call(
                    "compute_routes",
                    dest_lat=21.214,
                    dest_lng=105.807,
                    dest_name="Sân bay Nội Bài",
                    routing_mode="fast",
                ),
                call(
                    "compute_routes",
                    dest_lat=21.214,
                    dest_lng=105.807,
                    dest_name="Sân bay Nội Bài",
                    routing_mode="eco",
                ),
                {"poi_name": "Sân bay Nội Bài", "routing_mode": "eco"},
            ),
            "media_phone": (
                "media_phone_base_004",
                "Mở radio 91.0 FM.",
                {
                    "north": "Không, chuyển sang 95.6 FM.",
                    "central": "À không, chuyển sang 95.6 FM.",
                    "south": "Hông, qua 95.6 FM.",
                },
                call("media_control", command="tune", target="91.0", media_type="radio"),
                call("media_control", command="tune", target="95.6", media_type="radio"),
                {"radio_frequency": "95.6"},
            ),
        },
        "cancel_before_commit": {
            "automotive": (
                "base_024_drive_sport_confirm",
                "Chuyển chế độ lái sport.",
                {
                    "north": "Thôi hủy.",
                    "central": "Thôi hủy giúp.",
                    "south": "Thôi khỏi.",
                },
                call("drive_system", device="drive_mode", value="sport"),
                None,
                {},
            ),
            "navigation": (
                "navigation_base_010",
                "Dẫn đến Hồ Gươm.",
                {
                    "north": "Thôi hủy.",
                    "central": "Thôi hủy giúp.",
                    "south": "Thôi khỏi.",
                },
                call("compute_routes", dest_lat=21.029, dest_lng=105.852, dest_name="Hồ Gươm"),
                None,
                {},
            ),
            "media_phone": (
                "media_phone_base_005",
                "Gọi anh Nam.",
                {
                    "north": "Thôi hủy.",
                    "central": "Thôi hủy giúp.",
                    "south": "Thôi khỏi.",
                },
                call("phone_manager", intent="confirm_call", target="anh Nam"),
                None,
                {},
            ),
        },
    }
    index = 1
    for repair_mode, by_domain in mode_specs.items():
        for domain in ("automotive", "navigation", "media_phone"):
            base_task_id, initial_text, repair_by_accent, initial_call, final_call, slots = by_domain[domain]
            for accent in accents:
                rows.append(
                    golden_fdrc(
                        domain=domain,
                        accent=accent,
                        repair_mode=repair_mode,
                        index=index,
                        base_task_id=base_task_id,
                        initial_text=initial_text,
                        repair_text=repair_by_accent[accent],
                        initial_call=initial_call,
                        final_call=final_call,
                        slots=slots,
                    )
                )
                index += 1
    return rows


def main() -> None:
    dump_jsonl(SPEECH / "fdrc_golden_dataset.jsonl", build_golden_fdrc())


if __name__ == "__main__":
    main()
