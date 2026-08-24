"""One aggregate for the console's overview.

A dashboard that makes eight requests renders in eight stages; this returns
the whole picture in one, which also keeps "what the platform currently
knows" defined in a single place.
"""

from typing import Any

from fastapi import APIRouter, Request
from sqlalchemy import func, select

from app.core.db import get_sessionmaker
from app.core.graph_runtime import TERMINAL_STATUSES
from app.models.dispatch import Dispatch
from app.models.run import Run

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

WAITING_ON_HUMAN = "awaiting_gate_"
WAITING_ON_MACHINE = "awaiting_qa_execution"


def _classify(status: str) -> str:
    if status in TERMINAL_STATUSES:
        return "finished"
    if status.startswith(WAITING_ON_HUMAN):
        return "awaiting_human"
    if status == WAITING_ON_MACHINE:
        return "awaiting_machine"
    return "working"


@router.get("")
async def dashboard(request: Request) -> dict[str, Any]:
    async with get_sessionmaker()() as session:
        by_status = dict(
            (await session.execute(select(Run.status, func.count()).group_by(Run.status))).all()
        )
        recent = (
            await session.execute(select(Run).order_by(Run.created_at.desc()).limit(6))
        ).scalars().all()
        dispatch_states = dict(
            (
                await session.execute(
                    select(Dispatch.state, func.count()).group_by(Dispatch.state)
                )
            ).all()
        )

    buckets: dict[str, int] = {}
    for status, count in by_status.items():
        buckets[_classify(status)] = buckets.get(_classify(status), 0) + count

    graph = request.app.state.context_graph
    counts = await graph.counts()
    untested = await graph.untested_criteria()
    criteria_total = counts["nodes"].get("ACCEPTANCE_CRITERION", 0)

    settings = request.app.state.settings
    return {
        "runs": {
            "total": sum(by_status.values()),
            "by_status": by_status,
            "awaiting_human": buckets.get("awaiting_human", 0),
            "awaiting_machine": buckets.get("awaiting_machine", 0),
            "working": buckets.get("working", 0),
            "finished": buckets.get("finished", 0),
        },
        "recent": [
            {
                "run_id": str(r.id),
                "status": r.status,
                "created_at": r.created_at.isoformat(),
                "requirement": r.raw_requirement_text,
                "waiting_on": _classify(r.status),
            }
            for r in recent
        ],
        "coverage": {
            "criteria": criteria_total,
            "untested": len(untested),
            "tested": max(criteria_total - len(untested), 0),
            "gaps": [
                {"id": c["external_id"], "text": c["projection"].get("text", "")}
                for c in untested[:6]
            ],
        },
        "graph": {
            "nodes": counts["nodes"],
            "edges": counts["edges"],
            "modules": counts["nodes"].get("MODULE", 0),
            "dependencies": counts["edges"].get("DEPENDS_ON", 0),
        },
        "dispatches": dispatch_states,
        "active": {
            "model_provider": settings.llm_provider_adapter,
            "execution_target": settings.work_dispatch_adapter,
            "index_source": settings.code_intelligence_adapter,
            "indexed_repo": settings.code_index_repo,
            "gates": "auto-approved" if settings.auto_approve_gates else "human",
        },
    }
