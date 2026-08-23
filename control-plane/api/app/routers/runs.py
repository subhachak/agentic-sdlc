import asyncio
import json
import uuid
from typing import Any

from fastapi import APIRouter, Form, HTTPException, Request
from langgraph.types import Command
from sqlalchemy import select
from sse_starlette.sse import EventSourceResponse

from app.agents.state import PipelineConfig
from app.core.audit import summarize
from app.core.db import get_sessionmaker
from app.core.graph_runtime import TERMINAL_STATUSES, execute_run
from app.models.audit_log import AuditLog
from app.models.run import Run
from app.schemas.run import ApproveRequest, ApproveResponse, AuditEntryOut, CreateRunResponse, RunDetail, RunSummary

router = APIRouter(prefix="/runs", tags=["runs"])

POLL_INTERVAL_S = 1.0


def _spawn(request: Request, run_id: str, graph_input: Any) -> None:
    """Guard against two concurrent astream/ainvoke loops racing on the same
    checkpoint thread — mirrors the duplicate-launch guard every LangGraph
    FastAPI integration needs.
    """
    active_tasks: dict[str, asyncio.Task] = request.app.state.active_tasks
    if run_id in active_tasks and not active_tasks[run_id].done():
        raise HTTPException(status_code=409, detail="run already has an active task")

    async def _run() -> None:
        try:
            await execute_run(request.app.state.graph, run_id, graph_input)
        finally:
            active_tasks.pop(run_id, None)

    active_tasks[run_id] = asyncio.create_task(_run())


@router.post("", status_code=201)
async def create_run(request: Request, text: str = Form(...)) -> CreateRunResponse:
    run_id = str(uuid.uuid4())
    async with get_sessionmaker()() as session:
        session.add(Run(id=uuid.UUID(run_id), status="pending", raw_requirement_text=text))
        await session.commit()

    settings = request.app.state.settings
    initial_state = {
        "run_id": run_id,
        "config": PipelineConfig(
            auto_approve_gates=settings.auto_approve_gates, max_node_retries=settings.max_node_retries
        ),
        "raw_input": {"text": text, "file_bytes": None, "filename": None},
    }
    _spawn(request, run_id, initial_state)
    return CreateRunResponse(run_id=run_id, status="pending")


@router.get("")
async def list_runs() -> list[RunSummary]:
    async with get_sessionmaker()() as session:
        result = await session.execute(select(Run).order_by(Run.created_at.desc()))
        runs = result.scalars().all()
    return [
        RunSummary(
            run_id=str(r.id),
            status=r.status,
            created_at=r.created_at.isoformat(),
            raw_requirement_text=r.raw_requirement_text,
        )
        for r in runs
    ]


@router.get("/{run_id}")
async def get_run(request: Request, run_id: str) -> RunDetail:
    async with get_sessionmaker()() as session:
        run = await session.get(Run, uuid.UUID(run_id))
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")

    snapshot = await request.app.state.graph.aget_state({"configurable": {"thread_id": run_id}})
    pending_gate: dict | None = None
    for task in snapshot.tasks:
        if task.interrupts:
            pending_gate = task.interrupts[0].value
            break

    return RunDetail(
        run_id=run_id,
        status=run.status,
        state=summarize(dict(snapshot.values)),
        pending_gate=pending_gate,
    )


@router.post("/{run_id}/approve")
async def approve_gate(request: Request, run_id: str, body: ApproveRequest) -> ApproveResponse:
    async with get_sessionmaker()() as session:
        run = await session.get(Run, uuid.UUID(run_id))
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")

    payload = {"approved": body.approved, "feedback": body.feedback}
    _spawn(request, run_id, Command(resume=payload))
    return ApproveResponse(run_id=run_id, status="resuming")


@router.get("/{run_id}/audit")
async def get_audit_trail(run_id: str) -> list[AuditEntryOut]:
    async with get_sessionmaker()() as session:
        result = await session.execute(
            select(AuditLog).where(AuditLog.run_id == uuid.UUID(run_id)).order_by(AuditLog.created_at)
        )
        rows = result.scalars().all()
    return [
        AuditEntryOut(
            node_name=row.node_name,
            phase=row.phase,
            input_summary=row.input_summary,
            output_summary=row.output_summary,
            confidence_score=row.confidence_score,
            confirmed=row.confirmed,
            human_decision=row.human_decision,
            timestamp=row.created_at.isoformat(),
        )
        for row in rows
    ]


@router.get("/{run_id}/events")
async def stream_events(run_id: str, request: Request) -> EventSourceResponse:
    async def event_generator():
        seen_ids: set[str] = set()
        while True:
            if await request.is_disconnected():
                break

            async with get_sessionmaker()() as session:
                result = await session.execute(
                    select(AuditLog).where(AuditLog.run_id == uuid.UUID(run_id)).order_by(AuditLog.created_at)
                )
                rows = result.scalars().all()
                run = await session.get(Run, uuid.UUID(run_id))

            for row in rows:
                row_id = str(row.id)
                if row_id in seen_ids:
                    continue
                seen_ids.add(row_id)
                yield {
                    "event": "audit",
                    "data": json.dumps(
                        {
                            "node_name": row.node_name,
                            "phase": row.phase,
                            "output_summary": row.output_summary,
                            "confirmed": row.confirmed,
                            "human_decision": row.human_decision,
                            "timestamp": row.created_at.isoformat(),
                        }
                    ),
                }

            if run is not None and run.status in TERMINAL_STATUSES:
                yield {"event": "done", "data": json.dumps({"status": run.status})}
                break

            await asyncio.sleep(POLL_INTERVAL_S)

    return EventSourceResponse(event_generator())
