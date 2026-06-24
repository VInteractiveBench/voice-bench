# src/adapters/gemini_live_vivi_adapter.py
from __future__ import annotations

from typing import Any

from .base_vivi_agent_adapter import NormalizedEvent


def _strip_unsupported(parameters: dict) -> dict:
    """Gemini accepts an OpenAPI subset: drop OpenAI-only keys recursively."""
    cleaned = {}
    for key, value in parameters.items():
        if key in {"additionalProperties", "strict"}:
            continue
        if key == "properties" and isinstance(value, dict):
            cleaned[key] = {k: _strip_unsupported(v) if isinstance(v, dict) else v for k, v in value.items()}
        elif isinstance(value, dict):
            cleaned[key] = _strip_unsupported(value)
        else:
            cleaned[key] = value
    return cleaned


def to_gemini_tools(openai_schemas: list[dict]) -> list[dict]:
    declarations = [
        {
            "name": schema["name"],
            "description": schema.get("description", ""),
            "parameters": _strip_unsupported(schema.get("parameters", {})),
        }
        for schema in openai_schemas
    ]
    return [{"function_declarations": declarations}]


def normalize_gemini_message(message: Any, *, t_ms: int, speaking: bool) -> list[NormalizedEvent]:
    """Pure mapping from a Gemini Live message to NormalizedEvent list.

    `speaking` is whether assistant_speech_start has already been emitted for the
    current turn; the caller owns that flag and updates it from the returned events.
    """
    events: list[NormalizedEvent] = []

    if getattr(message, "data", None):
        if not speaking:
            events.append({"type": "assistant_speech_start", "t_ms": t_ms})
        events.append({"type": "assistant_audio_delta", "t_ms": t_ms})
        return events

    sc = getattr(message, "server_content", None)
    if sc is not None:
        out_tx = getattr(sc, "output_transcription", None)
        if out_tx is not None and getattr(out_tx, "text", None):
            events.append({"type": "assistant_transcript_delta", "t_ms": t_ms, "text": out_tx.text})
        in_tx = getattr(sc, "input_transcription", None)
        if in_tx is not None and getattr(in_tx, "text", None):
            events.append({"type": "user_transcript_done", "t_ms": t_ms, "text": in_tx.text})
        if getattr(sc, "interrupted", None):
            events.append({"type": "assistant_yielded", "t_ms": t_ms})
        if getattr(sc, "turn_complete", None):
            events.append({"type": "assistant_speech_stop", "t_ms": t_ms})

    tc = getattr(message, "tool_call", None)
    if tc is not None:
        for call in getattr(tc, "function_calls", None) or []:
            events.append({
                "type": "tool_call",
                "t_ms": t_ms,
                "tool": getattr(call, "name", ""),
                "args": dict(getattr(call, "args", {}) or {}),
                "call_id": getattr(call, "id", "") or getattr(call, "name", ""),
            })

    return events
