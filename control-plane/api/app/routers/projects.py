"""Projects: the engagements this deployment serves.

Separate from configuration because they are a different kind of thing. A
setting is a value someone changes; a project is a record someone creates,
with a name, a start date, and its own answers to the handful of questions
that differ between engagements.
"""

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.core import projects
from app.graph.projects import ProjectError

router = APIRouter(prefix="/projects", tags=["projects"])


class ProjectCreate(BaseModel):
    id: str
    name: str = ""
    description: str = ""
    engagement: dict[str, Any] = {}


class ProjectUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    engagement: dict[str, Any] | None = None


def _handle(exc: ProjectError) -> HTTPException:
    return HTTPException(status_code=422, detail=str(exc))


@router.get("")
async def list_projects(request: Request, include_archived: bool = False) -> dict:
    settings = request.app.state.settings
    await projects.ensure_default(settings)
    records = await projects.list_all(include_archived=include_archived)
    return {
        "active": settings.active_project,
        # What a new project starts from, so the console can show the fields
        # pre-filled rather than blank and let someone correct the two that
        # differ instead of typing all thirteen.
        "defaults": projects.defaults_from(settings),
        "engagement_keys": list(projects.ENGAGEMENT_KEYS),
        "projects": [record.as_dict() for record in records],
    }


@router.post("", status_code=201)
async def create_project(request: Request, body: ProjectCreate) -> dict:
    settings = request.app.state.settings
    try:
        record = await projects.create(
            body.id,
            name=body.name,
            description=body.description,
            engagement={**projects.defaults_from(settings), **body.engagement},
        )
    except ProjectError as exc:
        raise _handle(exc) from exc
    return record.as_dict()


@router.put("/{project_id}")
async def update_project(request: Request, project_id: str, body: ProjectUpdate) -> dict:
    try:
        record = await projects.update(
            project_id,
            name=body.name,
            description=body.description,
            engagement=body.engagement,
        )
    except ProjectError as exc:
        raise _handle(exc) from exc

    # Re-point the adapters if the project that just changed is the live one.
    # Without this an edit to the active engagement takes effect on the next
    # restart, which is exactly the kind of quiet lag that has someone
    # indexing the previous client's repository.
    if request.app.state.settings.active_project == record.id:
        from app.main import reload_runtime

        await reload_runtime(request.app)
    return record.as_dict()


@router.post("/{project_id}/activate")
async def activate_project(request: Request, project_id: str) -> dict:
    from app.core import settings_store
    from app.main import reload_runtime

    if await projects.get(project_id) is None:
        raise HTTPException(status_code=404, detail=f"no project {project_id!r}")

    await settings_store.save({"active_project": project_id})
    await reload_runtime(request.app)

    active_runs = sum(
        1 for task in request.app.state.active_tasks.values() if not task.done()
    )
    return {
        "active": project_id,
        "active_runs": active_runs,
        "warning": (
            f"{active_runs} run(s) are mid-flight and were started against the "
            f"previous project."
            if active_runs
            else None
        ),
    }


@router.post("/{project_id}/archive")
async def archive_project(project_id: str) -> dict:
    try:
        await projects.archive(project_id)
    except ProjectError as exc:
        raise _handle(exc) from exc
    return {"archived": project_id}


@router.delete("/{project_id}")
async def delete_project(project_id: str) -> dict:
    """Only for one created by mistake. The graph is left alone — purging a
    client's indexed code is a separate, explicit act."""
    try:
        await projects.delete_forever(project_id)
    except ProjectError as exc:
        raise _handle(exc) from exc
    return {"deleted": project_id}
