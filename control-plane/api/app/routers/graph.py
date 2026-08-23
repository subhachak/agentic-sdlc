"""Graph endpoints that are not scoped to a single run.

Seeding indexes a repository and writes its component and dependency
structure. It is separate from the run-scoped endpoints because the code
intelligence graph describes the codebase, not any one delivery.
"""

from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.core import seeding

router = APIRouter(prefix="/graph", tags=["graph"])


class SeedRequest(BaseModel):
    repo: str | None = None
    ref: str | None = None


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
    )


@router.get("/components")
async def list_components(request: Request) -> dict:
    """Components and their dependencies, as derived from the last index."""
    graph = request.app.state.context_graph
    return {"counts": await graph.counts(), "components": await graph.components()}
