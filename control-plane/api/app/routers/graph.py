"""Graph endpoints that are not scoped to a single run.

Seeding indexes a repository and writes its module and dependency
structure. It is separate from the run-scoped endpoints because the code
intelligence graph describes the codebase, not any one delivery.
"""

import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.core import hydration, seeding
from app.core.config import REPO_ROOT
from app.core.graph_export import build_export

router = APIRouter(prefix="/graph", tags=["graph"])


class ExportRequest(BaseModel):
    # The subtree the consumer actually tests. Scoping is not only about size:
    # a QA run testing demo-app should not be told a change reaches the
    # control plane's own modules.
    scope: str = "demo-app"


class SeedRequest(BaseModel):
    repo: str | None = None
    ref: str | None = None
    # Derived structure is rebuilt rather than accumulated. Pass false only to
    # layer an index on top of an existing one, which is rarely what you want.
    rebuild: bool = True


@router.post("/seed")
async def seed_graph(request: Request, body: SeedRequest) -> dict:
    """Point the platform at a repository and derive its structure.

    Reads source and parses imports; it never executes anything it fetches.
    """
    settings = request.app.state.settings
    repo = body.repo or settings.code_index_repo or ""
    ref = body.ref or settings.code_index_ref

    async with _indexing_errors(repo, ref):
        return await seeding.seed(
            request.app.state.context_graph,
            request.app.state.adapters.code_intelligence,
            repo=repo,
            ref=ref,
            rebuild=body.rebuild,
        )


@asynccontextmanager
async def _indexing_errors(repo: str, ref: str):
    """Turn an indexing failure into an answer someone can act on.

    A missing repository, an unreachable ref or an absent token are all
    ordinary setup mistakes, and the console is where they get made. Letting
    them surface as a 500 and a stack trace means the person doing first-time
    setup has to read server logs to find out they typed the wrong branch.

    Only ValueError and OSError are caught, deliberately. An adapter that
    speaks HTTP wraps its own transport failures — a router catching httpx
    would be coupled to the fact that one particular adapter uses it.
    """
    try:
        yield
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"could not read {repo or '(no repository configured)'}@{ref}: {exc}",
        ) from exc


def _export_path(settings) -> Path:
    """Resolved against the repository, not the process's working directory.

    The API is started from control-plane/api, so a relative path in settings
    resolved to a file beside the service rather than the one the execution
    plane reads — reporting "not written" for a file that was there.
    """
    configured = Path(settings.qa_export_path)
    return configured if configured.is_absolute() else REPO_ROOT / configured


@router.get("/status")
async def hydration_status(request: Request) -> dict:
    """What is populated and what is not, step by step.

    "Is it set up" has more than one answer — the graph can be indexed while
    retrieval is unbuilt and the execution plane's export describes a commit
    from last week. Each degrades differently, so each is reported.
    """
    settings = request.app.state.settings
    return await hydration.status(
        request.app.state.context_graph,
        request.app.state.adapters.code_design_context,
        _export_path(settings),
    )


@router.post("/refresh")
async def refresh_graph(request: Request, body: SeedRequest) -> dict:
    """Bring the graph up to date and report what moved.

    A rebuild produces the same graph. This exists because "the same graph"
    is not the same answer as "four files appeared, two are gone, eleven
    edges moved" — a graph that updates invisibly is one nobody can audit.
    """
    settings = request.app.state.settings
    repo = body.repo or settings.code_index_repo or ""
    ref = body.ref or settings.code_index_ref
    async with _indexing_errors(repo, ref):
        return await seeding.refresh(
            request.app.state.context_graph,
            request.app.state.adapters.code_intelligence,
            repo=repo,
            ref=ref,
        )


@router.post("/export")
async def write_export(request: Request, body: ExportRequest) -> dict:
    """Write the graph the execution plane reads.

    It runs in client CI with no route to this database, so the handover is a
    generated file rather than a query. Written here so first-time setup is
    something someone can do from the console instead of a script they have
    to be told about.
    """
    settings = request.app.state.settings
    export = await build_export(request.app.state.context_graph, scope=body.scope)
    if not export["modules"]:
        raise HTTPException(
            status_code=409,
            detail=f"nothing to export for scope {body.scope!r} — index the repository first",
        )

    path = _export_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(export, indent=2) + "\n")
    return {
        "path": str(path),
        "scope": body.scope,
        "modules": len(export["modules"]),
        "depends_on": len(export["depends_on"]),
        "routes": len(export.get("routes") or {}),
        "commit_sha": export["provenance"].get("commit_sha"),
    }


@router.post("/retrieval/rebuild")
async def rebuild_retrieval(request: Request) -> dict:
    """Build the index the design agent is grounded in.

    Otherwise it happens lazily on whichever request arrives first, which
    means the first design phase of a session pays for it and nobody can tell
    whether it worked.
    """
    retrieval = request.app.state.adapters.code_design_context
    rebuild = getattr(retrieval, "rebuild", None)
    if rebuild is None:
        raise HTTPException(
            status_code=409,
            detail="the configured grounding adapter has no index to build",
        )
    return await rebuild()


@router.get("/modules")
async def list_components(request: Request) -> dict:
    """Modules and their dependencies, as derived from the last index."""
    graph = request.app.state.context_graph
    return {"counts": await graph.counts(), "modules": await graph.modules()}


@router.get("/export")
async def export_graph(request: Request, scope: str = "") -> dict:
    """The derived graph in the form the execution plane consumes.

    Served rather than shared, because the execution plane runs in client CI
    with no route to this database. The provenance stamp travels with it so a
    QA run can refuse a graph that describes a commit it is not testing.
    """
    return await build_export(request.app.state.context_graph, scope=scope)
