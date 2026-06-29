from __future__ import annotations

import unicodedata
from typing import Any

from .common import state_diff
from .failure_taxonomy import is_blocking  # noqa: F401


def normalize_value(value: Any) -> Any:
    """Casefold + strip diacritics + collapse whitespace. Non-strings pass through."""
    if not isinstance(value, str):
        return value
    decomposed = unicodedata.normalize("NFD", value)
    without_marks = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return " ".join(without_marks.casefold().split())


def _normalize_struct(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _normalize_struct(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize_struct(item) for item in value]
    return normalize_value(value)


def deep_subset_normalized(expected: Any, actual: Any) -> bool:
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(
            key in actual and deep_subset_normalized(value, actual[key])
            for key, value in expected.items()
        )
    if isinstance(expected, list):
        return (
            isinstance(actual, list)
            and len(expected) == len(actual)
            and all(deep_subset_normalized(e, a) for e, a in zip(expected, actual))
        )
    return normalize_value(expected) == normalize_value(actual)


def state_matches_normalized(expected: Any, actual: Any) -> bool:
    """Mirror common.state_diff (subset on expected keys) but normalize leaves."""
    return state_diff(_normalize_struct(expected), _normalize_struct(actual))["matches"]


def _call_matches_normalized(wanted: dict, call: dict) -> bool:
    return wanted.get("tool") == call.get("tool") and deep_subset_normalized(
        wanted.get("args", {}), call.get("args", {})
    )


def tool_calls_covered(expected_calls: list[dict], committed_calls: list[dict]) -> bool:
    """Every expected call has a matching committed call; extra committed calls allowed."""
    return all(
        any(_call_matches_normalized(wanted, call) for call in committed_calls)
        for wanted in expected_calls
    )


def argument_match_normalized(
    expected_calls: list[dict], committed_calls: list[dict]
) -> bool:
    """For expected calls whose tool name was actually called, args subset-match."""
    relevant = [
        wanted
        for wanted in expected_calls
        if any(wanted.get("tool") == call.get("tool") for call in committed_calls)
    ]
    return all(
        any(_call_matches_normalized(wanted, call) for call in committed_calls)
        for wanted in relevant
    )
