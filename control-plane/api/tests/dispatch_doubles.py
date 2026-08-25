"""In-memory doubles for the dispatch seam, so its failure modes can be
exercised without a database, a CI system, or the passage of real time."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from app.core.dispatches import RESOLVED_STATES, DispatchRecord
from app.ports.work_dispatch import DispatchHandle, DispatchResult


def _now() -> datetime:
    return datetime.now(timezone.utc)


class InMemoryDispatchStore:
    def __init__(self) -> None:
        self.rows: dict[str, DispatchRecord] = {}

    def _find(self, run_id: str, phase: str) -> DispatchRecord | None:
        return next(
            (r for r in self.rows.values() if r.run_id == run_id and r.phase == phase), None
        )

    async def get(self, run_id: str, phase: str) -> DispatchRecord | None:
        return self._find(run_id, phase)

    async def claim(self, run_id, phase, provider, timeout_seconds):
        if self._find(run_id, phase) is not None:
            return None  # the unique constraint, in miniature
        record = DispatchRecord(
            id=uuid.uuid4().hex,
            run_id=run_id,
            phase=phase,
            provider=provider,
            correlation_id=uuid.uuid4().hex,
            state="pending",
            created_at=_now(),
            deadline_at=_now() + timedelta(seconds=timeout_seconds),
        )
        self.rows[record.id] = record
        return record

    async def attach_external(self, dispatch_id, external_id, external_url):
        row = self.rows[dispatch_id]
        row.external_id = external_id or row.external_id
        row.external_url = external_url or row.external_url

    async def resolve(self, dispatch_id, result: DispatchResult):
        row = self.rows[dispatch_id]
        if row.state in RESOLVED_STATES:
            return
        row.state = result.state
        row.result_payload = result.payload
        row.evidence_ref = result.evidence_ref
        row.detail = result.detail

    async def mark_applied(self, dispatch_id):
        row = self.rows[dispatch_id]
        if row.applied_at is None:
            row.applied_at = _now()

    async def list_pending(self):
        return [r for r in self.rows.values() if r.state == "pending"]

    async def list_unapplied(self):
        return [r for r in self.rows.values() if r.state in RESOLVED_STATES and r.applied_at is None]

    def expire_all(self) -> None:
        """Push every deadline into the past, instead of sleeping."""
        for row in self.rows.values():
            row.deadline_at = _now() - timedelta(seconds=1)


class StubWorkDispatch:
    """Records every trigger, and reports whatever the test tells it to."""

    def __init__(self, result: DispatchResult | None = None) -> None:
        self.triggers: list[tuple[str, str]] = []
        # Recorded so a test can assert which provider a row was polled by —
        # phases no longer share one, and a row started by one adapter must
        # not be checked against another.
        self.checked: list[str] = []
        self.result = result or DispatchResult(state="pending")

    async def trigger(
        self, run_id: str, phase: str, correlation_id: str, inputs: dict
    ) -> DispatchHandle:
        self.triggers.append((run_id, phase))
        return DispatchHandle(
            provider="stub", correlation_id=correlation_id, external_id=f"ext-{len(self.triggers)}"
        )

    async def check(self, handle: DispatchHandle) -> DispatchResult:
        self.checked.append(handle.correlation_id)
        return self.result


class ExplodingWorkDispatch(StubWorkDispatch):
    async def trigger(
        self, run_id: str, phase: str, correlation_id: str, inputs: dict
    ) -> DispatchHandle:
        raise RuntimeError("CI is unreachable")


SUCCESS = DispatchResult(
    state="succeeded",
    payload={"gate_passed": True, "evidence_summary": {"screenshot_count": 2, "trace_count": 2}},
    evidence_ref="https://ci.example/run/1",
)
