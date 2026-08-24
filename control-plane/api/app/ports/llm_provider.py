"""Port: model backend abstraction.

Demo adapters: Claude direct (via the `anthropic` SDK) and a deterministic
mock (no network) that proves the config-driven swap. Future: Azure AI
Foundry, OpenAI.
"""

from typing import Any, Protocol, TypeVar

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

    async def complete_json(
        self, system_prompt: str, user_prompt: str, schema: Any, *, max_tokens: int = 16000
    ) -> Any:
        """Return a validated instance of `schema`.

        Separate from `complete` because a phase that acts on the answer needs
        a shape it can rely on. Parsing prose into that shape afterwards is
        where these pipelines break: one stray token and the run dies with a
        JSON error three frames deep.
        """
        ...


T = TypeVar("T", bound=BaseModel)
