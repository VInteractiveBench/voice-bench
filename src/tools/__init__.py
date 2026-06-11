from .vivi_tool_schema import get_openai_tool_schemas

__all__ = [
    "MockToolServer",
    "ToolExecutionResult",
    "get_openai_tool_schemas",
]


def __getattr__(name: str):
    if name in {"MockToolServer", "ToolExecutionResult"}:
        from .mock_tool_server import MockToolServer, ToolExecutionResult

        return {
            "MockToolServer": MockToolServer,
            "ToolExecutionResult": ToolExecutionResult,
        }[name]
    raise AttributeError(name)
