from __future__ import annotations

from typing import Any

from speech_interaction.tools.vivi_tool_registry import SPECS

def _numeric_string(value: Any, low: float, high: float) -> bool:
    try:
        return low <= float(value) <= high
    except (TypeError, ValueError):
        return False


def validate_tool_schema(tool_name: str, arguments: dict) -> list[dict]:
    spec = SPECS.get(tool_name)
    if spec is None:
        return []
    errors = []
    allowed = set(spec["required"]) | set(spec["optional"])
    for key, kind in spec["required"].items():
        if key not in arguments:
            errors.append({"field": key, "reason": "required"})
        elif not isinstance(arguments[key], kind):
            errors.append({"field": key, "reason": "invalid_type"})
    for key, value in arguments.items():
        if key not in allowed:
            errors.append({"field": key, "reason": "unknown_parameter"})
            continue
        # OpenAI strict schemas require every field to be present, so the model
        # sends null for unused optional fields. Treat null optionals as absent.
        if value is None and key in spec["optional"]:
            continue
        kind = spec["required"].get(key, spec["optional"].get(key))
        if not isinstance(value, kind):
            errors.append({"field": key, "reason": "invalid_type"})
        if key in spec["enums"] and value not in spec["enums"][key]:
            errors.append({"field": key, "reason": "invalid_enum"})

    device = arguments.get("device")
    value = arguments.get("value")
    if tool_name == "climate_control":
        ranges = {"temp": (16, 30), "fan": (0, 8)}
        if device in ranges and not _numeric_string(value, *ranges[device]):
            errors.append({"field": "value", "reason": "out_of_range"})
        if device in {"ac", "defrost", "recirculation", "steering_heat"} and value not in {"true", "false"}:
            errors.append({"field": "value", "reason": "invalid_boolean_string"})
        if device == "fan_direction" and value not in {"face", "feet"}:
            errors.append({"field": "value", "reason": "invalid_enum"})
    if tool_name == "seat_control" and value not in {"true", "false", "1", "2", "3"}:
        errors.append({"field": "value", "reason": "invalid_enum"})
    if tool_name == "body_control" and value not in {"true", "false"} and not _numeric_string(value, 0, 100):
        errors.append({"field": "value", "reason": "invalid_boolean_or_percent"})
    if tool_name in {"body_control", "display_control", "light_control"} and device in {"window", "sunroof", "brightness", "ambient"}:
        if value not in {"true", "false", "blue", "red", "on", "off"} and not _numeric_string(value, 0 if device != "brightness" else 10, 100):
            errors.append({"field": "value", "reason": "out_of_range"})
    if tool_name == "drive_system" and device == "drive_mode" and value not in {"comfort", "sport", "eco"}:
        errors.append({"field": "value", "reason": "invalid_enum"})
    if tool_name == "comfort_control" and value not in {"true", "false", "ocean", "forest"}:
        errors.append({"field": "value", "reason": "invalid_enum"})
    if tool_name == "audio_control" and arguments.get("action") == "set":
        if "level" not in arguments or not isinstance(arguments["level"], int) or not 0 <= arguments["level"] <= 100:
            errors.append({"field": "level", "reason": "required_range_0_100"})
    if tool_name == "media_control" and arguments.get("command") in {"play", "search", "tune", "source"} and "target" not in arguments:
        errors.append({"field": "target", "reason": "required_for_command"})
    if tool_name == "media_control" and arguments.get("command") == "seek" and "value" not in arguments:
        errors.append({"field": "value", "reason": "required_for_command"})
    if tool_name == "phone_manager" and arguments.get("intent") in {"call", "search", "complaint", "confirm_call"} and "target" not in arguments:
        errors.append({"field": "target", "reason": "required_for_intent"})
    if tool_name == "check_traffic" and not any(k in arguments for k in ("location_query", "lat", "lng")):
        errors.append({"field": "location", "reason": "one_location_required"})
    return errors
