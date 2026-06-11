from __future__ import annotations

from speech_interaction.tools.vivi_tool_registry import MVP_TOOLS, OFFICIAL_TOOLS

from .failure_taxonomy import FailureType


def validate_tool_scope(tool_name: str, expected_tools: set[str] | None = None) -> str | None:
    if tool_name not in OFFICIAL_TOOLS:
        return FailureType.TOOL_NOT_IN_WHITELIST
    if tool_name not in MVP_TOOLS:
        return FailureType.OUT_OF_SCOPE_TOOL_CALL
    if expected_tools is not None and tool_name not in expected_tools:
        return FailureType.TOOL_SELECTION_ERROR
    return None
