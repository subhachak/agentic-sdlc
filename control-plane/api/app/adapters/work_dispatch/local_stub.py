"""Demo-default adapter: pretends to run a phase, with no CI involved.

Exists so the pipeline is demonstrable end to end on a laptop with no
GitHub repository, no token, and no network — and so the reconciler's
timing behaviour can be exercised deterministically in tests.
"""

from __future__ import annotations

import time
from typing import Any

from app.ports.work_dispatch import DispatchHandle, DispatchResult

def _n(node_type: str, system: str, external_id: str, **projection) -> dict:
    return {"type": node_type, "system": system, "external_id": external_id,
            "projection": projection}


_RUN = _n("TEST_RUN", "qa", "local-stub#1", status="passed")

# Shaped exactly like what the real QA pipeline emits, so the graph is
# populated on a laptop with no CI. Note that claims-status-filter/ac-3 is
# verified by a scenario that never reached a run — it is the criterion the
# release-readiness query should flag.
_CANNED_ASSERTIONS = [
    {"edge": "VERIFIED_BY",
     "src": _n("ACCEPTANCE_CRITERION", "features", "claims-list/ac-1",
               text="Table renders one row per claim"),
     "dst": _n("TEST_SCENARIO", "qa", "claims-table-renders", title="Claims table renders")},
    {"edge": "IMPLEMENTED_BY",
     "src": _n("TEST_SCENARIO", "qa", "claims-table-renders"),
     "dst": _n("TEST_SCRIPT", "qa", "claims-table-renders.spec.ts", mode="selected")},
    {"edge": "EXERCISED_IN",
     "src": _n("TEST_SCRIPT", "qa", "claims-table-renders.spec.ts"), "dst": _RUN},

    {"edge": "VERIFIED_BY",
     "src": _n("ACCEPTANCE_CRITERION", "features", "claims-status-filter/ac-2",
               text="Selecting a status shows only matching rows"),
     "dst": _n("TEST_SCENARIO", "qa", "filter-denied", title="Filtering by Denied")},
    {"edge": "IMPLEMENTED_BY",
     "src": _n("TEST_SCENARIO", "qa", "filter-denied"),
     "dst": _n("TEST_SCRIPT", "qa", "filter-denied.spec.ts", mode="generated")},
    {"edge": "EXERCISED_IN",
     "src": _n("TEST_SCRIPT", "qa", "filter-denied.spec.ts"), "dst": _RUN},

    # Planned, never executed — the gap the graph exists to surface.
    {"edge": "VERIFIED_BY",
     "src": _n("ACCEPTANCE_CRITERION", "features", "claims-status-filter/ac-3",
               text="A status with zero matches shows the empty state"),
     "dst": _n("TEST_SCENARIO", "qa", "filter-empty-state", title="Empty state")},

    {"edge": "COVERS",
     "src": _n("TEST_SCENARIO", "qa", "filter-denied"),
     "dst": _n("MODULE", "code", "claims-filter")},
    {"edge": "DEPENDS_ON",
     "src": _n("MODULE", "code", "claims-filter"),
     "dst": _n("MODULE", "code", "claims-api")},

    {"edge": "PRODUCED", "src": _RUN,
     "dst": _n("EVIDENCE", "qa", "evidence/html-report/index.html", screenshots=2, traces=2)},
]

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
    "assertions": _CANNED_ASSERTIONS,
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
