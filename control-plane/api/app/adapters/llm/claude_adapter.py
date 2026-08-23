"""ONLY file in the repo that imports `anthropic` — enforced by
tests/test_architecture_purity.py.
"""

import anthropic

from app.ports.llm_provider import LLMResponse


class ClaudeLLMProvider:
    def __init__(self, api_key: str | None, model: str) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._model = model

    async def complete(self, system_prompt: str, user_prompt: str, *, max_tokens: int = 1024) -> LLMResponse:
        response = await self._client.messages.create(
            model=self._model,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        text = "".join(block.text for block in response.content if block.type == "text")
        return LLMResponse(
            text=text,
            model=response.model,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )
