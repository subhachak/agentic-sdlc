"""Phase 3 — Test data: deterministic seeding, not agent-generated.

Seeding does not need judgment, it needs to guarantee coverage: every row a
scenario depends on has to exist before the test runs. This node is a pure
function of the test plan — no LLM call.

The plan states what it needs, in `required_data`, and this node provides it.
It used to guess instead: a regex over the scenario text against three
hardcoded status strings. The first run against a real planner proposed a
scenario about a fourth status, the guess found nothing, nothing was seeded,
and the test failed at run time complaining about data that had never been
created. Declared requirements make that failure impossible — an
unsatisfiable one is reported here, not discovered three phases later.
"""
from __future__ import annotations

from typing import Any

from orchestrator import data_store
from orchestrator.state import PipelineState


def _requirements(scenarios: list[dict]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for scenario in scenarios:
        for requirement in scenario.get("required_data") or []:
            out.append({**requirement, "scenario_id": scenario.get("id", "?")})
    return out


def run(state: PipelineState) -> PipelineState:
    store = data_store.load()
    shape = data_store.shape(store)

    added: list[str] = []
    unsatisfiable: list[str] = []

    for requirement in _requirements(state.get("test_plan", [])):
        entity = requirement.get("entity", "")
        field = requirement.get("field", "")
        value = str(requirement.get("value", ""))
        count = max(1, int(requirement.get("count", 1) or 1))

        if entity not in shape or field not in shape[entity]:
            unsatisfiable.append(
                f"{requirement['scenario_id']}: no {entity}.{field} in the data store"
            )
            continue

        rows = store[entity]
        have = sum(1 for row in rows if str(row.get(field)) == value)
        for _ in range(count - have):
            row = data_store.make_row(rows, entity, field, value)
            rows.append(row)
            added.append(f"{row['id']} ({field}={value})")

    if added:
        data_store.save(store)

    if unsatisfiable:
        summary = "Could not satisfy: " + "; ".join(unsatisfiable)
    elif added:
        summary = f"Seeded {len(added)} fixture(s): {', '.join(added)}."
    else:
        summary = "The data store already satisfied every declared requirement."

    return {
        **state,
        "seed_summary": summary,
        "seed_unsatisfiable": unsatisfiable,
        "seed_file": str(data_store.DATA_STORE),
    }
