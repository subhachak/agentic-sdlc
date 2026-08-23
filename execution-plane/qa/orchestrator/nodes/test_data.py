"""Phase 3 — Test data: deterministic seeding, not agent-generated.

Data seeding doesn't need judgment, it needs to guarantee coverage: every
status/value a scenario's expected_outcome references has to actually
exist in the data store before the test runs. This node is a pure
function of the test plan — no LLM call.
"""
from __future__ import annotations

import json
import re

from orchestrator.paths import DATA_STORE
from orchestrator.state import PipelineState

_KNOWN_STATUSES = ["Under Review", "Approved", "Denied"]


def _statuses_referenced(scenarios: list[dict]) -> set[str]:
    referenced = set()
    for sc in scenarios:
        text = f"{sc.get('title', '')} {sc.get('expected_outcome', '')}"
        for status in _KNOWN_STATUSES:
            if re.search(status, text, re.IGNORECASE):
                referenced.add(status)
    return referenced


def run(state: PipelineState) -> PipelineState:
    store = json.loads(DATA_STORE.read_text())
    claims = store["claims"]

    needed = _statuses_referenced(state.get("test_plan", []))
    present = {c["status"] for c in claims}
    missing = needed - present

    added = []
    next_id = max(int(c["id"].split("-")[1]) for c in claims) + 1
    for status in sorted(missing):
        new_claim = {
            "id": f"CLM-{next_id}",
            "policyholder": "Seeded Fixture",
            "status": status,
            "lastUpdated": "2026-08-20",
        }
        claims.append(new_claim)
        added.append(new_claim["id"])
        next_id += 1

    if added:
        DATA_STORE.write_text(json.dumps(store, indent=2) + "\n")

    summary = (
        f"Data store already covered {sorted(present)}."
        if not added
        else f"Added fixtures {added} to cover statuses referenced by the test plan: {sorted(needed)}."
    )

    return {
        **state,
        "seed_summary": summary,
        "seed_file": str(DATA_STORE),
    }
