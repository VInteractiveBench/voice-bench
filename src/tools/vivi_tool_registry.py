from __future__ import annotations

from typing import Any

POSITIONS = {"driver", "passenger", "front", "rear", "all"}
SEAT_POSITIONS = {"driver", "passenger", "rear_left", "rear_right", "all"}
BODY_POSITIONS = {"driver", "passenger", "rear_left", "rear_right", "rear", "front", "all"}

OFFICIAL_TOOLS = {
    "climate_control", "seat_control", "body_control", "light_control",
    "audio_control", "display_control", "connectivity_control", "drive_system",
    "comfort_control", "search_places", "compute_routes", "map_control",
    "saved_places", "check_traffic", "weather", "news_search", "web_search",
    "vinfast_kb", "vehicle_troubleshoot", "software_release", "media_control",
    "phone_manager", "lifestyle", "movie", "zodiac",
}

MVP_TOOLS = OFFICIAL_TOOLS - {
    "weather", "news_search", "web_search", "vinfast_kb",
    "vehicle_troubleshoot", "software_release",
}

SPECS: dict[str, dict[str, Any]] = {
    "climate_control": {"required": {"device": str, "value": str}, "optional": {"position": str, "unit": str}, "enums": {"device": {"ac", "temp", "fan", "defrost", "fan_direction", "recirculation", "steering_heat"}, "position": POSITIONS, "unit": {"C", "F"}}},
    "seat_control": {"required": {"device": str, "value": str}, "optional": {"position": str}, "enums": {"device": {"seat_cool", "seat_heat", "massage"}, "position": SEAT_POSITIONS}},
    "body_control": {"required": {"device": str, "value": str}, "optional": {"position": str}, "enums": {"device": {"window", "sunroof", "sunroof_shade", "mirror", "lock", "trunk", "charge_port"}, "position": BODY_POSITIONS}},
    "light_control": {"required": {"device": str, "value": str}, "optional": {"position": str}, "enums": {"device": {"ambient", "cabin_light", "headlight", "fog_light"}, "position": {"front", "rear", "all"}}},
    "audio_control": {"required": {"device": str, "action": str}, "optional": {"level": int}, "enums": {"device": {"all", "entertainment", "phone_ringing", "phone_in_call", "voice_assistant", "navigation", "reduce_chime"}, "action": {"mute", "unmute", "set", "reset"}}},
    "display_control": {"required": {"device": str, "value": str}, "optional": {}, "enums": {"device": {"brightness"}}},
    "connectivity_control": {"required": {"device": str, "value": str}, "optional": {}, "enums": {"device": {"wifi", "bluetooth", "wifi_hotspot"}}},
    "drive_system": {"required": {"device": str, "value": str}, "optional": {}, "enums": {"device": {"drive_mode", "regen_brake", "adas_settings"}}},
    "comfort_control": {"required": {"device": str, "value": str}, "optional": {}, "enums": {"device": {"perfume_diffuser", "privacy_mode"}}},
    "search_places": {"required": {"query": str}, "optional": {"category": str, "lat": (int, float), "lng": (int, float), "radius": (int, float), "max_results": int, "location_query": str, "route_id": str, "time_offset": int, "distance_offset_km": (int, float), "open_now": bool}, "enums": {"category": {"gas_station", "charging_station", "restaurant", "parking", "hospital", "hotel", "atm", "pharmacy", "cafe"}}},
    "compute_routes": {"required": {}, "optional": {"action": str, "dest_name": str, "dest_lat": (int, float), "dest_lng": (int, float), "origin_lat": (int, float), "origin_lng": (int, float), "via_waypoints": list, "avoid": list, "routing_mode": str, "num_alternatives": int}, "enums": {"action": {"calculate", "alternatives", "route_info"}, "routing_mode": {"fast", "short", "eco", "low_traffic"}}},
    "map_control": {"required": {"action": str}, "optional": {"view": str, "theme": str, "orientation": str}, "enums": {"action": {"set_view", "set_theme", "orientation", "start_navigation", "stop_navigation"}, "view": {"2d", "3d"}, "theme": {"default", "satellite"}, "orientation": {"north_up", "heading_up"}}},
    "saved_places": {"required": {"action": str}, "optional": {"label": str, "lat": (int, float), "lng": (int, float), "address": str, "title": str}, "enums": {"action": {"save", "list"}}},
    "check_traffic": {"required": {}, "optional": {"location_query": str, "lat": (int, float), "lng": (int, float), "radius": int}, "enums": {}},
    "media_control": {"required": {"command": str}, "optional": {"target": str, "media_type": str, "value": int}, "enums": {"command": {"play", "pause", "stop", "next", "prev", "seek", "tune", "search", "source", "shuffle", "repeat", "browse", "list_playlists", "set_volume"}, "media_type": {"music", "radio", "podcast", "audiobook"}}},
    "phone_manager": {"required": {"intent": str}, "optional": {"target": str, "history_filter": str}, "enums": {"intent": {"call", "search", "history", "complaint", "confirm_call", "cancel_call"}, "history_filter": {"all", "missed", "incoming", "outgoing"}}},
    "lifestyle": {"required": {"query": str}, "optional": {"category": str, "location": str}, "enums": {"category": {"travel", "food", "culture"}}},
    "movie": {"required": {"query": str}, "optional": {"intent": str, "cinema": str, "date": str}, "enums": {"intent": {"showtimes", "info", "booking"}}},
    "zodiac": {"required": {}, "optional": {"sign": str, "topic": str}, "enums": {"topic": {"daily", "weekly", "monthly", "personality", "love", "career", "compatibility"}}},
}

IN_SCOPE_TOOLS = tuple(sorted(MVP_TOOLS))

DOMAIN_TOOLS = {
    "automotive": {
        "climate_control",
        "seat_control",
        "body_control",
        "light_control",
        "audio_control",
        "display_control",
        "connectivity_control",
        "drive_system",
        "comfort_control",
    },
    "navigation": {
        "search_places",
        "compute_routes",
        "map_control",
        "saved_places",
        "check_traffic",
    },
    "media_phone": {
        "media_control",
        "phone_manager",
        "lifestyle",
        "movie",
        "zodiac",
    },
}


def get_domain_tools(domain: str) -> list[str]:
    return sorted(DOMAIN_TOOLS[domain])


def get_tool_spec(tool_name: str) -> dict:
    return SPECS[tool_name]
