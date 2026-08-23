import contextlib
from contextlib import asynccontextmanager

import asyncio

import aiosqlite
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from app.adapters.registry import build_adapters
from app.agents.graph import build_graph
from app.agents.nodes import build_nodes
from app.core.audit import AuditLogger
from app.core.config import get_settings
from app.core.db import init_db
from app.core.dispatches import SqlDispatchStore
from app.core.gate_controller import GateController
from app.core.reconciler import run_forever
from app.routers import health, runs


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.settings = settings

    await init_db()

    adapters = build_adapters(settings)
    app.state.adapters = adapters

    dispatch_store = SqlDispatchStore()
    app.state.dispatch_store = dispatch_store
    audit_logger = AuditLogger(adapters.audit_sink)
    gate_controller = GateController(audit_logger)

    nodes = build_nodes(
        requirements_source=adapters.requirements_source,
        code_design_context=adapters.code_design_context,
        test_management=adapters.test_management,
        build_deploy=adapters.build_deploy,
        work_dispatch=adapters.work_dispatch,
        dispatch_store=dispatch_store,
        llm_provider=adapters.llm_provider,
        audit_logger=audit_logger,
        gate_controller=gate_controller,
        max_retries=settings.max_node_retries,
        dispatch_timeout_seconds=settings.dispatch_timeout_seconds,
        dispatch_provider=settings.work_dispatch_adapter,
    )

    # Our own pydantic models (PipelineConfig, GateDecision, ConfidenceEntry)
    # ride in graph state and get checkpointed — register them explicitly so
    # the checkpointer's msgpack serde doesn't warn (and, in a future
    # langgraph-checkpoint release, refuse) to deserialize an "unregistered"
    # type it doesn't recognize by default.
    serde = JsonPlusSerializer(
        allowed_msgpack_modules=[
            ("app.agents.state", "PipelineConfig"),
            ("app.agents.state", "GateDecision"),
            ("app.core.confidence", "ConfidenceEntry"),
        ]
    )
    async with aiosqlite.connect(settings.checkpointer_db_path) as conn:
        checkpointer = AsyncSqliteSaver(conn, serde=serde)
        app.state.graph = build_graph(nodes, checkpointer=checkpointer)
        app.state.active_tasks = {}
        # One reconciler for the process. It is what turns a finished CI job
        # into a resumed run, so nothing else needs to block waiting on one.
        reconciler = asyncio.create_task(
            run_forever(
                app.state.graph,
                adapters.work_dispatch,
                app.state.active_tasks,
                dispatch_store,
                settings.reconciler_interval_seconds,
            )
        )
        try:
            yield
        finally:
            reconciler.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await reconciler


app = FastAPI(title="Agentic SDLC Pipeline Accelerator (scaffold)", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[get_settings().web_origin],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, prefix="/api")
app.include_router(runs.router, prefix="/api")
