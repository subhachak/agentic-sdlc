"""The default: this platform's own agent, calling a model in-process.

Answers immediately, so it never returns `pending` and `read_result` is never
called on it. Kept as the default because it is the one implementation whose
behaviour is known here — a client's agent is a substitution, not an upgrade.
"""

from __future__ import annotations

from typing import Any

from app.agents.design import DesignProposal as DesignSchema
from app.agents.design import SYSTEM, build_prompt
from app.ports.design_agent import DesignOutcome, DesignProposal, DesignRequest
from app.ports.llm_provider import LLMProvider


class InlineDesignAgent:
    contract_version = 1

    def capabilities(self) -> dict:
        """In-process, answers in seconds, and reads its refusals.

        Declared rather than assumed, so the phase can tell a retry that
        will differ from one that will not.
        """
        return {"dispatched": False, "uses_feedback": True, "max_files": 15}

    def __init__(self, llm_provider: LLMProvider) -> None:
        self._llm = llm_provider

    async def propose(self, request: DesignRequest) -> DesignOutcome:
        prompt = build_prompt(
            requirement=request.requirement,
            criteria=request.criteria,
            catalogue=request.catalogue,
            snippets=request.context_snippets,
            max_files=request.max_files,
        )
        if request.rejected_reasons:
            prompt += (
                "\n\nYour previous design was rejected:\n"
                + "\n".join(f"- {reason}" for reason in request.rejected_reasons)
                + "\n\nName only modules and files from the catalogue above."
            )

        proposal = await self._llm.complete_json(SYSTEM, prompt, DesignSchema)
        return DesignOutcome(
            state="ready", proposal=DesignProposal(**proposal.model_dump())
        )

    def read_result(self, payload: dict[str, Any]) -> DesignProposal:
        # Unreachable for this adapter: it never returns `pending`. Defined so
        # the port is satisfied without a caller having to know which shape it
        # is talking to.
        raise NotImplementedError("the inline design agent answers synchronously")
