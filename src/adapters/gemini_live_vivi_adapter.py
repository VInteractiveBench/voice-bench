# src/adapters/gemini_live_vivi_adapter.py
from __future__ import annotations


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
