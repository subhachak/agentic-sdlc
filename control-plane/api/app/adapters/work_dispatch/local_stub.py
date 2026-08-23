"""Demo-default adapter: pretends to run a phase, with no CI involved.

Exists so the pipeline is demonstrable end to end on a laptop with no
GitHub repository, no token, and no network — and so the reconciler's
timing behaviour can be exercised deterministically in tests.
"""

from __future__ import annotations

import time
from typing import Any

from app.ports.work_dispatch import DispatchHandle, DispatchResult

_CANNED_PAYLOAD = {
    "gate_passed": True,
    "test_plan": [
        {"id": "claims-table-renders", "title": "Claims table renders every claim",
         "type": "regression", "priority": "P1"},
        {"id": "filter-denied", "title": "Filtering by Denied shows only denied claims",
         "type": "functional", "priority": "P1"},
    ],
    "gate_reasons": ["all planned scenarios ran and passed"],
    "evidence_summary": {"screenshot_count": 2, "trace_count": 2,
                         "html_report": "evidence/html-report/index.html"},
}


class LocalStubWorkDispatch:
    """Reports `pending` for `duration_seconds`, then succeeds."""

    def __init__(self, duration_seconds: float = 3.0) -> None:
        self._duration = duration_seconds
        self._started: dict[str, float] = {}

    async def trigger(
        self, run_id: str, phase: str, correlation_id: str, inputs: dict[str, Any]
    ) -> DispatchHandle:
        self._started[correlation_id] = time.monotonic()
        return DispatchHandle(
            provider="local-stub",
            correlation_id=correlation_id,
            external_id=f"local-{correlation_id[:8]}",
            external_url=None,
        )

    async def check(self, handle: DispatchHandle) -> DispatchResult:
        started = self._started.get(handle.correlation_id)
        if started is None or time.monotonic() - started < self._duration:
            return DispatchResult(state="pending")
        return DispatchResult(
            state="succeeded",
            payload=_CANNED_PAYLOAD,
            evidence_ref="local-stub://evidence",
            external_id=handle.external_id,
        )
