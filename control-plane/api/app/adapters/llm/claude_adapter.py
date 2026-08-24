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

    async def complete_json(
        self, system_prompt: str, user_prompt: str, schema, *, max_tokens: int = 16000
    ):
        """Structured output: the model is constrained to the schema and the
        SDK validates before this returns, so a caller never parses prose.

        Adaptive thinking is on — the implementation phase is the one place in
        this pipeline where the model is reasoning about existing code rather
        than restating a summary, and it is worth the tokens.
        """
        response = await self._client.beta.messages.parse(
            model=self._model,
            max_tokens=max_tokens,
            thinking={"type": "adaptive"},
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
            output_format=schema,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
        if response.stop_reason == "refusal":
            detail = getattr(response.stop_details, "explanation", None) or "no explanation"
            raise RuntimeError(f"the model declined this request: {detail}")
        if response.parsed_output is None:
            raise RuntimeError("the model returned no parsable output")
        return response.parsed_output
