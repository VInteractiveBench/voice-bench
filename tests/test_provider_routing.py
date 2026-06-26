from src.orchestrator.full_duplex_orchestrator import provider_for_agent


def test_provider_for_agent_maps_known_agents():
    assert provider_for_agent("openai_realtime") == "openai"
    assert provider_for_agent("openai_text") == "openai"
    assert provider_for_agent("gemini_live") == "google"


def test_provider_for_agent_unknown_returns_none():
    assert provider_for_agent("something_else") is None
    assert provider_for_agent(None) is None


def test_realtime_uses_non_strict_schemas():
    # openai_realtime / gemini_live must request non-strict schemas so optional
    # fields are not forced into `required`.
    from src.orchestrator.full_duplex_orchestrator import tool_schemas_for_agent

    realtime = {s["name"]: s for s in tool_schemas_for_agent("openai_realtime", "media_phone")}
    assert realtime["media_control"]["parameters"]["required"] == ["command"]
    assert "strict" not in realtime["media_control"]

    text = {s["name"]: s for s in tool_schemas_for_agent("openai_text", "media_phone")}
    assert "value" in text["media_control"]["parameters"]["required"]
    assert text["media_control"]["strict"] is True
