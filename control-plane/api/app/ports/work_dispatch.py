"""Port: run a lifecycle phase somewhere else and find out how it went.

Demo adapter: a local stub that needs no CI at all. Real adapter: GitHub
Actions. Future: Jenkins, Azure DevOps, Harness.

Deliberately two methods, both about the remote job. The port never resumes
the graph — that belongs to core/reconciler.py — which is what keeps
CI-shaped concerns out of the deterministic core.
"""

from typing import Any, Literal, Protocol

from pydantic import BaseModel


class DispatchHandle(BaseModel):
    provider: str
    correlation_id: str
    # Unknown at trigger time for providers whose trigger call returns no id
    # (workflow_dispatch is one), resolved on the first check().
    external_id: str | None = None
    external_url: str | None = None


class DispatchResult(BaseModel):
    state: Literal["pending", "succeeded", "failed", "timed_out"]
    payload: dict[str, Any] | None = None
    evidence_ref: str | None = None
    detail: str | None = None
    external_id: str | None = None
    external_url: str | None = None


class WorkDispatch(Protocol):
    async def trigger(
        self, run_id: str, phase: str, correlation_id: str, inputs: dict[str, Any]
    ) -> DispatchHandle: ...
    """`correlation_id` is minted by the caller when it reserves the
    dispatch row, not by the adapter. The row is the record of truth, so an
    adapter that generated its own nonce would be tagging the remote job
    with an id nothing on this side can match it back to."""

    async def check(self, handle: DispatchHandle) -> DispatchResult: ...
