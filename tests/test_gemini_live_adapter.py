# tests/test_gemini_live_adapter.py
from src.adapters.gemini_live_vivi_adapter import to_gemini_tools


def test_to_gemini_tools_strips_openai_only_keys():
    openai_schemas = [
        {
            "type": "function",
            "name": "climate_control",
            "description": "Set climate.",
            "parameters": {
                "type": "object",
                "properties": {"device": {"type": "string"}},
                "required": ["device"],
                "additionalProperties": False,
            },
            "strict": True,
        }
    ]
    tools = to_gemini_tools(openai_schemas)
    assert tools == [
        {
            "function_declarations": [
                {
                    "name": "climate_control",
                    "description": "Set climate.",
                    "parameters": {
                        "type": "object",
                        "properties": {"device": {"type": "string"}},
                        "required": ["device"],
                    },
                }
            ]
        }
    ]


def test_to_gemini_tools_empty():
    assert to_gemini_tools([]) == [{"function_declarations": []}]
