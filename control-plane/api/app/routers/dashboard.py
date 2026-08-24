"""One aggregate for the console's overview.

A dashboard that makes eight requests renders in eight stages; this returns
the whole picture in one, which also keeps "what the platform currently
knows" defined in a single place.
"""

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from sqlalchemy import func, select

from app.core import hydration
from app.core.config import REPO_ROOT
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
    provenance = await graph.index_provenance()
    hydration_state = await hydration.status(
        graph,
        request.app.state.adapters.code_design_context,
        _export_path(settings),
    )
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
        # What this deployment is pointed at, separated from how it runs.
        # A dashboard that shows throughput without showing which repository
        # produced it is a number with no subject.
        "engagement": {
            # What is *indexed*, not what is configured to be indexed next
            # time. Reading the setting alone reported "not set" while a graph
            # sat there holding a repository someone had already indexed.
            "indexed_repo": provenance.get("repo") or settings.code_index_repo,
            "indexed_ref": settings.code_index_ref,
            "target_repo": settings.target_repo,
            "target_ref": settings.target_ref,
            "environment": settings.target_environment,
            "ci_repo": settings.github_repo,
            "export_scope": settings.qa_export_scope,
            "commit": provenance.get("commit_sha"),
            "indexed_at": provenance.get("indexed_at"),
        },
        "platform": {
            "model_provider": settings.llm_provider_adapter,
            "model": settings.claude_model,
            "execution_target": settings.work_dispatch_adapter,
            "index_source": settings.code_intelligence_adapter,
            "change_target": settings.source_control_adapter,
            "gates": "auto-approved" if settings.auto_approve_gates else "human",
        },
        "credentials": {
            "anthropic_api_key": bool(settings.anthropic_api_key),
            "github_token": bool(settings.github_token),
        },
        # Whether the platform is ready to run at all, and if not, which step
        # is missing. Surfaced here because the dashboard is where someone
        # looks first, and "no runs yet" and "nothing is indexed" look alike.
        "hydration": {
            "hydrated": hydration_state["hydrated"],
            "steps": [
                {"id": s["id"], "title": s["title"], "ready": s["ready"], "detail": s["detail"]}
                for s in hydration_state["steps"]
            ],
        },
        # Kept for the console's older reads. Superseded by engagement/platform.
        "active": {
            "model_provider": settings.llm_provider_adapter,
            "execution_target": settings.work_dispatch_adapter,
            "index_source": settings.code_intelligence_adapter,
            "indexed_repo": settings.code_index_repo,
            "gates": "auto-approved" if settings.auto_approve_gates else "human",
        },
    }


def _export_path(settings) -> Path:
    """Resolved against the repository, not the process's working directory."""
    configured = Path(settings.qa_export_path)
    return configured if configured.is_absolute() else REPO_ROOT / configured
