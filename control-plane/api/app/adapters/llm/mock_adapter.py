from app.ports.llm_provider import LLMResponse


class MockLLMProvider:
    """Deterministic echo adapter — zero network. Default adapter for this
    scaffold (runs with no API key), and the second half of the config-driven
    LLMProvider swap smoke test alongside ClaudeLLMProvider.
    """

    async def complete(self, system_prompt: str, user_prompt: str, *, max_tokens: int = 1024) -> LLMResponse:
        text = f"[MOCK] {user_prompt[:200]}"
        return LLMResponse(text=text, model="mock", input_tokens=len(user_prompt.split()), output_tokens=len(text.split()))

    async def complete_json(
        self, system_prompt: str, user_prompt: str, schema, *, max_tokens: int = 16000
    ):
        """The smallest instance of the schema that validates.

        Deliberately empty rather than plausible: a mock that invented file
        edits would let the implementation phase appear to work with no model
        behind it, which is the one thing a mock must never do.
        """
        fields = {}
        for name, field in schema.model_fields.items():
            if field.is_required():
                annotation = field.annotation
                fields[name] = (
                    ""
                    if annotation is str
                    else []
                    if annotation in (list, list[str])
                    else annotation()
                    if callable(annotation)
                    else None
                )
        instance = schema(**fields)
        if hasattr(instance, "blocked"):
            instance.blocked = (
                "the mock provider cannot write code — set LLM_PROVIDER_ADAPTER=claude"
            )
        if hasattr(instance, "summary"):
            instance.summary = "[MOCK] no change proposed"
        return instance
