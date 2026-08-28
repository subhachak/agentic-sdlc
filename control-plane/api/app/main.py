import contextlib
from contextlib import asynccontextmanager

import asyncio

import aiosqlite
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from app.adapters.registry import (
    build_adapters,
    build_context_graph_store,
    build_entity_resolver,
)
from app.agents.graph import build_graph
from app.agents.nodes import build_nodes
from app.core.audit import AuditLogger
from app.core.config import get_settings
from app.core.db import init_db
from app.core.context_graph import SqlContextGraph
from app.core.dispatches import SqlDispatchStore
from app.core.gate_controller import GateController
from app.core.reconciler import run_forever
from app.core import projects, settings_store
from app.routers import graph as graph_router
from app.routers import config as config_router
from app.routers import dashboard as dashboard_router
from app.routers import health, runs
from app.routers import projects as projects_router


def build_runtime(app: FastAPI, settings, checkpointer=None) -> None:
    """Construct everything that depends on configuration.

    Called at start-up and again whenever configuration changes. The registry
    is already a pure function of settings, so rebuilding is the whole of
    "apply this change" — and paused runs survive it, because their state
    lives in the checkpointer rather than in the compiled graph.
    """
    # The graph is built before the adapters because one of them reads it:
    # retrieval grounds the design agent in the same snapshot that impact and
    # containment are computed from, rather than indexing the repository a
    # second time on its own.
    context_graph = build_context_graph_store(settings)
    adapters = build_adapters(settings, graph=context_graph)
    app.state.settings = settings
    app.state.adapters = adapters
    app.state.context_graph = context_graph

    audit_logger = AuditLogger(adapters.audit_sink)
    nodes = build_nodes(
        requirements_source=adapters.requirements_source,
        code_design_context=adapters.code_design_context,
        test_management=adapters.test_management,
        build_deploy=adapters.build_deploy,
        work_dispatch=adapters.work_dispatch,
        source_control=adapters.source_control,
        code_intelligence=adapters.code_intelligence,
        implementation_agent=settings.implementation_agent,
        implementation_dispatch=adapters.implementation_dispatch,
        implementation_agent_port=adapters.implementation_agent,
        qa_agent=adapters.qa_agent,
        dispatch_store=app.state.dispatch_store,
        context_graph=app.state.context_graph,
        llm_provider=adapters.llm_provider,
        audit_logger=audit_logger,
        gate_controller=GateController(audit_logger),
        max_retries=settings.max_node_retries,
        dispatch_timeout_seconds=settings.dispatch_timeout_seconds,
        dispatch_provider=settings.work_dispatch_adapter,
        target_repo=settings.target_repo or "",
        target_ref=settings.target_ref,
        target_environment=settings.target_environment,
    )
    app.state.graph = build_graph(nodes, checkpointer=checkpointer or app.state.checkpointer)


async def reload_runtime(app: FastAPI) -> None:
    """Re-read configuration and rebuild. The reconciler picks the new
    instances up on its next tick, because it asks for them on every tick.

    The active project's engagement settings are layered on last, so
    switching project re-points the adapters at that codebase without
    anything else having to know a project exists.
    """
    base = get_settings()
    overrides = await settings_store.load_overrides()
    settings = settings_store.effective(base, overrides)

    await projects.ensure_default(settings)
    record = await projects.get(settings.active_project)
    effective = projects.applied_to(settings, record)

    problem: str | None = None
    failure: str | None = None
    for candidate, means in _fallbacks(base, effective, record, bool(overrides)):
        try:
            build_runtime(app, candidate)
        except Exception as exc:  # noqa: BLE001
            failure = str(exc)
            continue
        # The explanation belongs to the rung that worked, not the one that
        # did not: what an admin needs is what is running now and why, and
        # the error that caused the fall.
        problem = f"{means}{failure}" if means and failure else None
        break
    else:
        # Unreachable: the last fallback is a configuration with no external
        # dependency at all. Kept so a future adapter that breaks even that
        # fails loudly here rather than leaving `app.state.adapters` unset.
        raise RuntimeError(f"no configuration could be built: {failure}")

    app.state.config_problem = problem
    app.state.project = record


# Everything local, nothing credentialed. The configuration a fresh install
# has, and the one the platform falls back to so the console is always
# reachable — a control plane that will not start cannot be used to fix the
# setting that stopped it.
SAFE_MODE = {
    "llm_provider_adapter": "mock",
    "work_dispatch_adapter": "local",
    "implementation_agent": "inline",
    "source_control_adapter": "local",
    "code_intelligence_adapter": "local",
    "code_design_context_adapter": "stub",
    # The one adapter whose fallback matters more than reachability: safe
    # mode exists because something is already wrong, and an adapter that
    # merges pull requests is not something to leave armed while nobody
    # knows why the configuration failed.
    "build_deploy_adapter": "noop",
    "target_working_copy": ".",
    "code_index_local_root": ".",
}


def _fallbacks(base, effective, record, has_overrides: bool):
    """Configurations to try, best first, each with why the previous failed.

    Three rungs. What was asked for; the environment alone, in case a stored
    override is the problem; and a configuration with no external dependency
    at all, so the console comes up either way.
    """
    yield effective, ""
    if has_overrides:
        yield projects.applied_to(base, record), (
            "saved configuration could not be applied and was ignored: "
        )
    yield base.model_copy(update=SAFE_MODE), (
        "the platform started with every integration disabled because its "
        "configuration could not be applied: "
    )


def _dispatchers(app: FastAPI) -> dict[str, object]:
    settings = app.state.settings
    adapters = app.state.adapters
    out: dict[str, object] = {settings.work_dispatch_adapter: adapters.work_dispatch}
    if adapters.implementation_dispatch is not None:
        out[settings.implementation_agent] = adapters.implementation_dispatch
    return out


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    app.state.dispatch_store = SqlDispatchStore()
    app.state.active_tasks = {}

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
    base = get_settings()
    async with aiosqlite.connect(base.checkpointer_db_path) as conn:
        app.state.checkpointer = AsyncSqliteSaver(conn, serde=serde)
        await reload_runtime(app)

        reconciler = asyncio.create_task(
            run_forever(
                lambda: (
                    app.state.graph,
                    # Keyed by provider, because the phases no longer share
                    # one: QA may run in the client's CI while the change is
                    # written by their coding agent, and a row started by one
                    # cannot be polled by the other.
                    _dispatchers(app),
                    app.state.active_tasks,
                    app.state.dispatch_store,
                ),
                app.state.settings.reconciler_interval_seconds,
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
app.include_router(graph_router.router, prefix="/api")
app.include_router(config_router.router, prefix="/api")
app.include_router(dashboard_router.router, prefix="/api")
app.include_router(projects_router.router, prefix="/api")
