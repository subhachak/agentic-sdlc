"""Drives the compiled graph to completion or its next pause, and keeps the
`runs` row's status column in sync with the graph's own state.

`thread_id == run_id` — a 1:1 mapping between the DB run and the LangGraph
checkpoint thread, same convention used throughout this codebase.
"""

import uuid
from typing import Any

from app.core.db import get_sessionmaker
from app.models.run import Run

TERMINAL_STATUSES = {
    "completed",
    "rejected_at_gate_1",
    "rejected_at_gate_2",
    "rejected_at_gate_3",
    "requirements_intake_failed",
    "synthesis_failed",
    "ambiguity_check_failed",
    "design_proposal_failed",
    "test_case_generation_failed",
    "build_deploy_failed",
}


async def execute_run(graph: Any, run_id: str, graph_input: Any) -> dict[str, Any]:
    """`graph_input` is either the initial state dict (fresh run) or
    `Command(resume=payload)` (gate approval)."""
    thread = {"configurable": {"thread_id": run_id}, "recursion_limit": 50}
    result = await graph.ainvoke(graph_input, config=thread)
    await _sync_run_status(run_id, result)
    return result


async def _sync_run_status(run_id: str, result: dict[str, Any]) -> None:
    status = result.get("status")
    if status is None:
        return
    async with get_sessionmaker()() as session:
        run = await session.get(Run, uuid.UUID(run_id))
        if run is not None:
            run.status = status
            await session.commit()


def is_paused(result: dict[str, Any]) -> bool:
    return "__interrupt__" in result


def is_terminal(status: str) -> bool:
    return status in TERMINAL_STATUSES
