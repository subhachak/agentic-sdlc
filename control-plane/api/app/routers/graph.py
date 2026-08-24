"""Graph endpoints that are not scoped to a single run.

Seeding indexes a repository and writes its module and dependency
structure. It is separate from the run-scoped endpoints because the code
intelligence graph describes the codebase, not any one delivery.
"""

from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.core import seeding
from app.core.graph_export import build_export

router = APIRouter(prefix="/graph", tags=["graph"])


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

    return await seeding.seed(
        request.app.state.context_graph,
        request.app.state.adapters.code_intelligence,
        repo=repo,
        ref=ref,
        rebuild=body.rebuild,
    )


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
