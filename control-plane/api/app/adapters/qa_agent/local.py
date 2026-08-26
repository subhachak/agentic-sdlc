"""The framework's own QA pipeline, run inside its boundary.

The counterpart to the inline implementation agent: nothing leaves. Script
selection, generation, the data lifecycle and execution are the execution
plane's own ports — TestAuthor, TestDataProvider, TestRunner — and they run
against a working copy on this machine.

Still routed through the dispatch seam rather than awaited inline. A QA run
takes minutes and a build takes longer; blocking a phase coroutine on it
would mean a restart loses the run, and the row-and-reconciler machinery
already solves that. "Inside the boundary" is about where the work happens
and who sees the source, not about whether the phase waits synchronously.
"""

from __future__ import annotations

from typing import Any

from app.adapters.qa_agent.dispatched import DispatchedQAAgent
from app.ports.qa_agent import QARequest


class LocalQAAgent(DispatchedQAAgent):
    contract_version = 1

    def __init__(self, provider: str = "local-pipeline", dispatch: Any = None) -> None:
        super().__init__(provider=provider, dispatch=dispatch)

    def capabilities(self) -> dict[str, Any]:
        return {
            "dispatched": True,
            "authors_tests": True,
            "manages_test_data": True,
            "reports_coverage": True,
            # The distinction that matters to a client with a data
            # residency question. Everything above happens on infrastructure
            # this platform controls.
            "runs_in_platform_boundary": True,
        }

    async def execute(self, request: QARequest):
        outcome = await super().execute(request)
        # The local pipeline checks out a branch rather than a sha pair, so
        # it needs the branch to be present. Said here rather than failing
        # inside a subprocess three steps later.
        if not (request.branch or request.head_sha):
            return outcome.model_copy(
                update={
                    "state": "failed",
                    "detail": "the local QA pipeline needs a branch or a head revision to check out",
                }
            )
        return outcome
