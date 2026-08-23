"""Port: model backend abstraction.

Demo adapters: Claude direct (via the `anthropic` SDK) and a deterministic
mock (no network) that proves the config-driven swap. Future: Azure AI
Foundry, OpenAI.
"""

from typing import Protocol

from pydantic import BaseModel


class LLMResponse(BaseModel):
    text: str
    model: str
    input_tokens: int
    output_tokens: int


class LLMProvider(Protocol):
    async def complete(
        self, system_prompt: str, user_prompt: str, *, max_tokens: int = 1024
    ) -> LLMResponse: ...
