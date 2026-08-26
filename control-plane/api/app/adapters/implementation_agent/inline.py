"""This platform's own coding agent, calling a model in-process.

Answers in seconds and returns the edits themselves, so nothing is written
anywhere until the change has been reviewed against the graph. That ordering
is the difference between this and a dispatched agent: the client's agent
pushes a branch and is judged after the fact, and this one is judged before
anything exists.
"""

from __future__ import annotations

from typing import Any

from app.ports.implementation_agent import (
    FileChange,
    ImplementationOutcome,
    ImplementationRequest,
    ImplementationResult,
)


class InlineImplementationAgent:
    contract_version = 1

    def __init__(self, llm_provider: Any, system_prompt: str, schema: Any,
                 build_prompt: Any) -> None:
        self._llm = llm_provider
        self._system = system_prompt
        self._schema = schema
        self._build_prompt = build_prompt

    def capabilities(self) -> dict[str, Any]:
        return {
            "dispatched": False,
            "opens_pull_request": False,
            # It is *asked* to stay inside the allowed files, and reviewed
            # afterwards regardless. Declaring true here would claim a
            # guarantee that only the review provides.
            "honours_allowed_files": False,
            "max_files": 15,
        }

    async def implement(self, request: ImplementationRequest) -> ImplementationOutcome:
        proposal = await self._llm.complete_json(
            self._system,
            self._build_prompt(
                requirement=request.requirement,
                design={"summary": request.design_summary},
                criteria=request.criteria,
                files=request.sources,
                allowed_modules=request.allowed_modules,
            ),
            self._schema,
        )
        if getattr(proposal, "blocked", ""):
            return ImplementationOutcome(
                state="ready",
                result=ImplementationResult(
                    summary=getattr(proposal, "summary", ""),
                    blocked=proposal.blocked,
                ),
            )
        edits = [FileChange(path=e.path, content=e.content) for e in proposal.edits]
        return ImplementationOutcome(
            state="ready",
            result=ImplementationResult(
                summary=getattr(proposal, "summary", ""),
                edits=edits,
                files=[e.path for e in edits],
            ),
        )

    def read_result(self, payload: dict[str, Any]) -> ImplementationResult:
        # Never called: this agent is synchronous, so nothing is ever pending
        # for the reconciler to resume.
        raise NotImplementedError("the inline implementation agent does not dispatch")
