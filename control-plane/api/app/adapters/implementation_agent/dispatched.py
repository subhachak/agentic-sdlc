"""A client's coding agent, reached through the shared dispatch seam.

A typed façade rather than a second dispatch mechanism. Reserving a row,
triggering, parking and reconciling is the same problem whether the remote
worker is a CI job or an agent, and duplicating it would be worse than the
untyped dict this replaces. What this adds is a contract: what the agent is
given, and what its answer has to contain.

The phase still owns the dispatch row. This never resumes the graph — that
belongs to core/reconciler.py, which is what keeps CI-shaped concerns out of
the deterministic core.
"""

from __future__ import annotations

from typing import Any

from app.ports.implementation_agent import (
    ImplementationOutcome,
    ImplementationRequest,
    ImplementationResult,
)


class DispatchedImplementationAgent:
    contract_version = 1

    def __init__(self, provider: str, dispatch: Any) -> None:
        self._provider = provider
        self._dispatch = dispatch

    def capabilities(self) -> dict[str, Any]:
        return {
            "dispatched": True,
            "opens_pull_request": True,
            # Same as the inline agent, for the same reason: the constraint
            # is enforced by the review, not by the agent's good intentions.
            "honours_allowed_files": False,
            "max_files": 0,  # unbounded; containment is what bounds it
        }

    async def implement(self, request: ImplementationRequest) -> ImplementationOutcome:
        """Describe the work; the phase starts it.

        Returning the inputs rather than calling trigger() keeps the dispatch
        row and the trigger in one place. An adapter that triggered on its own
        would be starting remote work the platform has no row for, and a
        crash between the two would leave an agent running that nothing is
        waiting on.
        """
        return ImplementationOutcome(
            state="pending",
            provider=self._provider,
            dispatch_inputs={
                "prompt": request.brief,
                "base_ref": request.base_ref,
                "repo": request.repo,
            },
        )

    def read_result(self, payload: dict[str, Any]) -> ImplementationResult:
        """What a finished dispatch means.

        The mapping that used to live inline in the phase, as untyped key
        reads. `head_ref` is the load-bearing one: without it there is no
        branch to review, and the change cannot be checked against the
        design at all.
        """
        return ImplementationResult(
            summary=payload.get("summary") or "",
            head_ref=payload.get("head_ref") or "",
            base_ref=payload.get("base_ref") or "",
            pull_request_id=str(payload.get("pull_request_id") or ""),
            head_sha=payload.get("head_sha") or "",
            base_sha=payload.get("base_sha") or "",
            url=payload.get("external_url") or "",
            files=list(payload.get("files") or []),
        )

    async def check_access(self) -> dict[str, Any]:
        """Optional capability, now declared rather than found by getattr."""
        prober = getattr(self._dispatch, "check_access", None)
        if prober is None:
            return {"ok": False, "detail": "this provider cannot be checked without starting work"}
        return await prober()
