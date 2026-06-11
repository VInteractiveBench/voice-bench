from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from speech_interaction.evaluator.tool_schema_validator import validate_tool_schema
from speech_interaction.evaluator.tool_scope_validator import validate_tool_scope
from speech_interaction.io import read_json, write_jsonl


@dataclass
class ToolExecutionResult:
    ok: bool
    content: dict
    validation_errors: list[dict]


class MockToolServer:
    """Local deterministic execution surface for the 19 in-scope Vivi tools."""

    def __init__(self, domain: str, task: dict, overlay: dict | None = None) -> None:
        self.domain = domain
        self.task = task
        self.overlay = overlay or {}
        self.db_path = Path("data") / "tau2" / "domains" / domain / "db.json"
        self.initial_state = deepcopy(task.get("initial_state", {}))
        self.state = self._load_state()
        self.tool_call_log: list[dict] = []
        self.tool_results: list[dict] = []

    def _load_state(self) -> dict:
        base = read_json(self.db_path) if self.db_path.exists() else {}
        base.update(deepcopy(self.initial_state))
        return base

    def execute(self, tool: str, args: dict, *, t_ms: int | None = None) -> ToolExecutionResult:
        errors = []
        scope_error = validate_tool_scope(tool)
        if scope_error:
            errors.append({"tool": tool, "reason": str(scope_error)})
        errors.extend({"tool": tool, **err} for err in validate_tool_schema(tool, args))
        call = {"tool": tool, "args": deepcopy(args)}
        if t_ms is not None:
            call["t_ms"] = t_ms
        self.tool_call_log.append(call)
        if errors:
            result = {"success": False, "error": "validation_failed", "errors": errors}
            self.tool_results.append(result)
            return ToolExecutionResult(False, result, errors)
        self._mutate(tool, args)
        result = {"success": True, "ok": True, "tool": tool, "message": self._message(tool, args)}
        self.tool_results.append(result)
        return ToolExecutionResult(True, result, [])

    def _mutate(self, tool: str, args: dict) -> None:
        if tool == "climate_control":
            climate = self.state.setdefault("climate", {})
            device = args["device"]
            value = args["value"]
            position = args.get("position") or "all"
            if device == "temp":
                temps = climate.setdefault("temperature_c", {})
                targets = ["driver", "passenger", "rear"] if position == "all" else [position]
                for target in targets:
                    temps[target] = float(value)
            elif device == "fan":
                climate["fan_level"] = int(value)
            else:
                climate[device] = value
        elif tool == "seat_control":
            seat = self.state.setdefault("seats", {}).setdefault(args.get("position") or "driver", {})
            key = {"seat_heat": "heat", "seat_cool": "cool", "massage": "massage"}[args["device"]]
            seat[key] = args["value"]
        elif tool == "body_control":
            body = self.state.setdefault("body", {})
            device = args["device"]
            if device == "window":
                body.setdefault("windows", {})[args.get("position") or "all"] = int(args["value"])
            else:
                body[device] = args["value"]
        elif tool in {"light_control", "audio_control", "display_control", "connectivity_control", "drive_system", "comfort_control"}:
            bucket = {
                "light_control": "lights",
                "audio_control": "audio",
                "display_control": "display",
                "connectivity_control": "connectivity",
                "drive_system": "drive",
                "comfort_control": "comfort",
            }[tool]
            self.state.setdefault(bucket, {})[args.get("device", "last")] = deepcopy(args)
        elif tool == "compute_routes":
            self.state.setdefault("navigation", {})["route"] = deepcopy(args)
        elif tool == "map_control":
            self.state.setdefault("navigation", {})["map"] = deepcopy(args)
        elif tool == "saved_places":
            self.state.setdefault("navigation", {}).setdefault("saved_places", []).append(deepcopy(args))
        elif tool == "search_places":
            self.state.setdefault("navigation", {})["last_search"] = deepcopy(args)
        elif tool == "check_traffic":
            self.state.setdefault("navigation", {})["last_traffic_check"] = deepcopy(args)
        elif tool == "media_control":
            self.state.setdefault("media", {})["last_command"] = deepcopy(args)
        elif tool == "phone_manager":
            self.state.setdefault("phone", {})["last_intent"] = deepcopy(args)
        elif tool in {"lifestyle", "movie", "zodiac"}:
            self.state.setdefault("media_phone", {})[tool] = deepcopy(args)

        expected = self.overlay.get("expected_tool_calls", self.task.get("expected_tool_calls", []))
        if self._matches_expected_prefix(expected):
            target_state = self.overlay.get(
                "expected_final_state", self.task.get("expected_final_state", {})
            )
            self.state.update(deepcopy(target_state))

    def _matches_expected_prefix(self, expected: list[dict]) -> bool:
        if len(self.tool_call_log) != len(expected):
            return False
        return all(
            actual["tool"] == wanted["tool"] and all(
                actual["args"].get(key) == value for key, value in wanted.get("args", {}).items()
            )
            for actual, wanted in zip(self.tool_call_log, expected)
        )

    def _message(self, tool: str, args: dict) -> str:
        return f"{tool} executed with {args}"

    def final_state(self) -> dict:
        return deepcopy(self.state)

    def save_tool_log(self, path: str | Path) -> None:
        write_jsonl(path, self.tool_call_log)
