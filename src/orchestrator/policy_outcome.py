"""Derive policy-gating episode signals from a live agent run.

Live providers return tool calls + an assistant transcript, but not the
structured decision the policy evaluator expects. This module derives the
``execute | clarify | refuse`` decision, the clarification targets, the
response-honesty flag, and the resulting vehicle ``final_state`` from what the
agent actually did, so a live run produces meaningful (non-oracle) metrics.
"""

from __future__ import annotations

from copy import deepcopy

# Vietnamese interrogatives that signal the agent asked a clarifying question.
_QUESTION_MARKERS = (
    "?", "nào", "gì", "ai ", " ai?", "đâu", "mấy", "bao nhiêu",
    "muốn", "ý bạn", "bạn cần", "cụ thể", "loại nào", "bên nào",
)
# Phrases that claim an action was completed.
_DONE_MARKERS = ("đã ", "xong", "rồi.", " rồi", "hoàn tất", "được rồi")


def _looks_like_question(transcript: list[str]) -> bool:
    text = " ".join(transcript).lower()
    return any(marker in text for marker in _QUESTION_MARKERS)


def _claims_done(transcript: list[str]) -> bool:
    text = " ".join(transcript).lower()
    return any(marker in text for marker in _DONE_MARKERS)


def derive_policy_decision(
    tool_calls: list[dict],
    assistant_transcript: list[str],
    must_ask_about: list[str],
) -> tuple[str, list[str], bool]:
    """Return (decision, clarification_targets, response_claims_execution)."""
    if tool_calls:
        return "execute", [], True
    if _looks_like_question(assistant_transcript):
        return "clarify", list(must_ask_about or []), False
    return "refuse", [], _claims_done(assistant_transcript)


def _truthy(value) -> bool:
    """Generic on/enabled check (climate booleans, seat heat, adas)."""
    return str(value).lower() in {"true", "on", "1"} or (
        str(value).replace(".", "", 1).isdigit() and float(value) > 0
    )


def _is_open(value) -> bool:
    return str(value).lower() in {"true", "open", "on", "1"} or (
        str(value).replace(".", "", 1).isdigit() and float(value) > 0
    )


def _is_unlock(value) -> bool:
    return str(value).lower() in {"false", "unlock", "off", "0"}


def apply_policy_tool_effects(vehicle_state: dict, tool_calls: list[dict]) -> dict:
    """Apply the agent's tool calls onto a copy of vehicle_state, using the same
    schema as the dataset's ``expected_final_state``."""
    state = deepcopy(vehicle_state) if isinstance(vehicle_state, dict) else {}
    for call in tool_calls or []:
        tool = call.get("tool")
        args = call.get("args", {}) if isinstance(call.get("args"), dict) else {}
        value = args.get("value")
        position = args.get("position") or "driver"
        if tool == "climate_control":
            climate = state.setdefault("climate", {})
            device = args.get("device")
            if device == "temp":
                try:
                    climate[position] = {"temperature_celsius": int(float(value))}
                except (TypeError, ValueError):
                    climate[position] = {"temperature_celsius": value}
            elif device == "fan":
                try:
                    climate["fan"] = int(float(value))
                except (TypeError, ValueError):
                    climate["fan"] = value
            else:
                climate[device] = _truthy(value)
        elif tool == "seat_control":
            state.setdefault("seat", {}).setdefault(position, {})["heat"] = (
                "on" if _truthy(value) else "off"
            )
        elif tool == "body_control":
            device = args.get("device")
            if device == "trunk":
                state["trunk_state"] = "open" if _is_open(value) else "closed"
            elif device == "lock":
                state["doors_locked"] = not _is_unlock(value)
            elif device == "window":
                state.setdefault("window", {})[args.get("position") or "all"] = value
            else:
                state[device] = value
        elif tool == "map_control":
            nav = state.setdefault("navigation", {})
            action = args.get("action")
            if action == "start_navigation":
                nav["active"] = True
            elif action == "stop_navigation":
                nav["active"] = False
        elif tool == "media_control":
            state.setdefault("media", {})["playing"] = True
        elif tool == "phone_manager":
            if args.get("intent") == "call":
                state.setdefault("phone", {})["call_state"] = "dialing"
        elif tool == "drive_system":
            if args.get("device") == "adas_settings":
                state.setdefault("adas", {})["enabled"] = _truthy(value)
    return state


def annotate_policy_episode(episode: dict, overlay: dict) -> dict:
    """Populate decision signals + vehicle final_state on a live policy episode."""
    vehicle_state = overlay.get("vehicle_state", {})
    must_ask = (overlay.get("required_question") or {}).get("must_ask_about", [])
    decision, targets, claims = derive_policy_decision(
        episode.get("tool_calls", []), episode.get("assistant_transcript", []), must_ask
    )
    episode["decision"] = decision
    episode["clarification_targets"] = targets
    episode["response_claims_execution"] = claims
    episode["initial_state"] = deepcopy(vehicle_state)
    episode["final_state"] = apply_policy_tool_effects(vehicle_state, episode.get("tool_calls", []))
    return episode
