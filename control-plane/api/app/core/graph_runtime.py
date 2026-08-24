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
    # A design naming modules that do not exist would make containment
    # meaningless downstream, so the run stops rather than proceeding.
    "design_rejected",
    "design_blocked",
    "test_case_generation_failed",
    "build_deploy_failed",
    "release_failed",
    # A change nobody would want proposed stops here rather than being run.
    "implementation_failed",
    "implementation_blocked",
    "implementation_rejected",
    # A remote execution that never produced a usable verdict ends the run.
    # Both must be listed here or stream_events never closes the SSE stream.
    "qa_failed",
    "qa_timed_out",
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


def spawn_run(active_tasks: dict, graph: Any, run_id: str, graph_input: Any) -> bool:
    """Start a graph task for `run_id`, unless one is already running.

    Returns False rather than raising when the thread is busy: the HTTP
    caller turns that into a 409, while the reconciler simply tries again on
    its next tick. That retry is what stops a result arriving before the
    graph has parked from being lost.
    """
    import asyncio

    existing = active_tasks.get(run_id)
    if existing is not None and not existing.done():
        return False

    async def _run() -> None:
        try:
            await execute_run(graph, run_id, graph_input)
        finally:
            active_tasks.pop(run_id, None)

    active_tasks[run_id] = asyncio.create_task(_run())
    return True
