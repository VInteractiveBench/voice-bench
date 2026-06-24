from __future__ import annotations

from typing import Any

from .vivi_tool_registry import get_domain_tools, get_tool_spec

DESCRIPTIONS = {
    "climate_control": "Control AC, temperature, fan, defrost, air direction, recirculation, and steering wheel heat. Use device=temp for Celsius setpoint, device=fan for fan level, device=defrost for windshield defrost.",
    "seat_control": "Control seat cooling, heating, and massage. Use position=driver/passenger/rear_left/rear_right/all when the user mentions a seat.",
    "body_control": "Control windows, sunroof, mirrors, locks, trunk, and charge port. Use device=window for window percentage commands and position for driver/passenger/rear/front.",
    "light_control": "Control ambient, cabin, headlight, and fog lights. Use value only within the tool enum, not free-form brightness words.",
    "audio_control": "Control in-car audio volume and mute state. Use action=mute/unmute/set/reset and level only for numeric volume.",
    "display_control": "Control central display brightness. Use device=brightness and value from the allowed enum/schema.",
    "connectivity_control": "Control Wi-Fi, Bluetooth, and Wi-Fi hotspot.",
    "drive_system": "Control drive mode, regenerative braking, and ADAS settings. Use device=drive_mode for eco/sport/normal-style driving mode commands.",
    "comfort_control": "Control perfume diffuser and privacy mode.",
    "search_places": "Search for places or points of interest.",
    "compute_routes": "Compute routes to a destination.",
    "map_control": "Control map display and active navigation state.",
    "saved_places": "Save or list favorite places.",
    "check_traffic": "Check traffic near a location.",
    "media_control": "Control music, radio, podcast, and media browsing.",
    "phone_manager": "Manage phone calls, contact search, call history, and complaints.",
    "lifestyle": "Search lifestyle, travel, food, and culture information.",
    "movie": "Search movie showtimes, information, or booking intent.",
    "zodiac": "Search zodiac information.",
}


def _json_type(py_type: Any) -> str | list[str]:
    if py_type is str:
        return "string"
    if py_type is int:
        return "integer"
    if py_type is bool:
        return "boolean"
    if py_type is list:
        return "array"
    if py_type == (int, float):
        return "number"
    return "string"


def _property_schema(name: str, py_type: Any, enum_values: set | None, *, nullable: bool) -> dict:
    json_type = _json_type(py_type)
    # OpenAI strict mode requires every property in `required`; optionality is
    # expressed by making only optional fields nullable. Required fields stay
    # non-nullable so the model cannot legally omit them with a null value.
    schema: dict[str, Any] = {"type": [json_type, "null"] if nullable else json_type}
    if json_type == "array":
        # OpenAI strict function schemas require array fields to define `items`.
        schema["items"] = {"type": "string"}
    if enum_values:
        schema["enum"] = sorted(enum_values) + ([None] if nullable else [])
    return schema


def tool_to_openai_schema(tool_name: str) -> dict:
    spec = get_tool_spec(tool_name)
    properties = {}
    required = []
    for field_name, field_type in spec["required"].items():
        properties[field_name] = _property_schema(
            field_name, field_type, spec["enums"].get(field_name), nullable=False
        )
        required.append(field_name)
    for field_name, field_type in spec["optional"].items():
        properties[field_name] = _property_schema(
            field_name, field_type, spec["enums"].get(field_name), nullable=True
        )
        required.append(field_name)
    return {
        "type": "function",
        "name": tool_name,
        "description": DESCRIPTIONS.get(tool_name, f"Vivi tool {tool_name}."),
        "parameters": {
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,
        },
        "strict": True,
    }


def get_openai_tool_schemas(domain: str | None = None) -> list[dict]:
    tool_names = get_domain_tools(domain) if domain else sorted(DESCRIPTIONS)
    return [tool_to_openai_schema(name) for name in tool_names]
