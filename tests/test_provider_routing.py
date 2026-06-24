from src.orchestrator.full_duplex_orchestrator import provider_for_agent


def test_provider_for_agent_maps_known_agents():
    assert provider_for_agent("openai_realtime") == "openai"
    assert provider_for_agent("openai_text") == "openai"
    assert provider_for_agent("gemini_live") == "google"


def test_provider_for_agent_unknown_returns_none():
    assert provider_for_agent("something_else") is None
    assert provider_for_agent(None) is None
