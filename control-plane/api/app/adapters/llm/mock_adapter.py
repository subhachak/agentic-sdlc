from app.ports.llm_provider import LLMResponse


class MockLLMProvider:
    """Deterministic echo adapter — zero network. Default adapter for this
    scaffold (runs with no API key), and the second half of the config-driven
    LLMProvider swap smoke test alongside ClaudeLLMProvider.
    """

    async def complete(self, system_prompt: str, user_prompt: str, *, max_tokens: int = 1024) -> LLMResponse:
        text = f"[MOCK] {user_prompt[:200]}"
        return LLMResponse(text=text, model="mock", input_tokens=len(user_prompt.split()), output_tokens=len(text.split()))
