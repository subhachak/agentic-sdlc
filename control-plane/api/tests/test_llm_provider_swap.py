"""Acceptance-criterion smoke test: swapping the LLMProvider adapter happens
in config alone, with zero node/router code touched.
"""

import pytest

from app.adapters.llm.mock_adapter import MockLLMProvider
from app.adapters.registry import build_llm_provider
from app.core.config import Settings


def test_llm_provider_adapter_swaps_purely_via_config():
    mock_settings = Settings(llm_provider_adapter="mock")
    assert isinstance(build_llm_provider(mock_settings), MockLLMProvider)

    claude_settings = Settings(
        llm_provider_adapter="claude",
        anthropic_api_key="sk-test-not-a-real-key",
        claude_model="claude-opus-5",
    )
    from app.adapters.llm.claude_adapter import ClaudeLLMProvider

    assert isinstance(build_llm_provider(claude_settings), ClaudeLLMProvider)


@pytest.mark.asyncio
async def test_mock_provider_completes_without_any_network_call():
    provider = MockLLMProvider()
    response = await provider.complete("system prompt", "hello world")
    assert response.text.startswith("[MOCK]")
    assert response.model == "mock"
