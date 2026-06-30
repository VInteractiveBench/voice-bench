"""Normalize fdrc_golden_enriched_v2_90.jsonl enum/shape typos in place.

Usage:
    C:\\Python314\\python -m scripts.normalize_v2_90
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

PATH = Path("fdrc_golden_enriched_v2_90.jsonl")


def _integerish(value: Any) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value)
    return None


def _fix_call(call: dict) -> dict:
    if not isinstance(call, dict):
        return call
    tool, args = call.get("tool"), call.get("args")
    if not isinstance(args, dict):
        return call
    if tool == "climate_control" and args.get("device") == "fan_speed":
        args["device"] = "fan"
    if tool == "compute_routes" and args.get("routing_mode") == "shortest":
        args["routing_mode"] = "short"
    if tool == "media_control":
        if args.get("command") == "set_volume":
            if "value" not in args:
                value = _integerish(args.get("target"))
                if value is not None:
                    args["value"] = value
            args.pop("target", None)
            args.pop("media_type", None)
        elif args.get("media_type") in {"audio", "call_audio"}:
            args["media_type"] = "music"
    return call


def _fix_overlay(overlay: dict) -> dict:
    for key in ("expected_tool_calls", "forbidden_tool_calls"):
        overlay[key] = [_fix_call(call) for call in overlay.get(key, [])]
    if isinstance(overlay.get("initial_intent"), dict):
        overlay["initial_intent"] = _fix_call(overlay["initial_intent"])
    slots = overlay.get("expected_critical_slots")
    if isinstance(slots, dict):
        if slots.get("device") == "fan_speed":
            slots["device"] = "fan"
        if slots.get("command") == "set_volume":
            if "value" not in slots:
                value = _integerish(slots.get("target"))
                if value is not None:
                    slots["value"] = value
            slots.pop("target", None)
            slots.pop("media_type", None)
        elif slots.get("media_type") in {"audio", "call_audio"}:
            slots["media_type"] = "music"
    return overlay


def main() -> None:
    rows = [
        json.loads(line)
        for line in PATH.read_text(encoding="utf-8-sig").splitlines()
        if line.strip()
    ]
    rows = [_fix_overlay(row) for row in rows]
    PATH.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )
    print(f"normalized {len(rows)} rows")


if __name__ == "__main__":
    main()
