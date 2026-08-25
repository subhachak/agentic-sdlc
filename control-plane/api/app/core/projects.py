"""Projects: the engagements this deployment serves.

The graph is already scoped by project. This is the rest of it — the record
someone creates when a new engagement starts, holding the handful of settings
that differ between them: which codebase, where changes go, where they ship.

Those settings used to live in the global settings table, which meant two
teams could not hold different answers at the same time. They are stored per
project now, with the environment's values as the seed for a new project and
the fallback when none exists — so a single-project deployment behaves as it
always did, and the default project is a real record rather than a special
case that has to be remembered everywhere.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import delete, select

from app.core.config import Settings, derive, undone
from app.core.db import get_sessionmaker
from app.graph.projects import DEFAULT_PROJECT, ProjectError
from app.graph.projects import validate as validate_id
from app.models.project import Project

# The settings that belong to an engagement rather than to the platform.
# Deliberately the same list the console shows under "this engagement": one
# place decides what is per-project, and both the API and the UI read it.
ENGAGEMENT_KEYS = (
    "code_index_repo",
    "code_index_ref",
    "code_index_max_depth",
    "code_index_local_root",
    "target_repo",
    "target_ref",
    "target_working_copy",
    "target_environment",
    "github_repo",
    "github_workflow_file",
    "github_ref",
    "qa_export_path",
    "qa_export_scope",
)


@dataclass
class ProjectRecord:
    id: str
    name: str
    description: str
    engagement: dict[str, Any]
    archived: bool
    created_at: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "engagement": self.engagement,
            "archived": self.archived,
            "created_at": self.created_at,
        }


# Keys derivation can supply. A stored value for one of these is only a
# decision when it differs from what derivation would have produced.
DERIVABLE = ("target_repo", "target_ref", "github_repo", "github_ref")


def _canonical(value: Any) -> Any:
    """A repository name reduced to one form.

    `https://github.com/acme/widgets` and `acme/widgets` are one repository
    written two ways, and treating them as different answers is how a value
    identical to the derived one reads as a deliberate override.
    """
    if not isinstance(value, str):
        return value
    text = value.strip().rstrip("/")
    for prefix in ("https://github.com/", "http://github.com/", "git@github.com:"):
        if text.startswith(prefix):
            text = text[len(prefix):]
    return text.removesuffix(".git").lower()


def redundant(engagement: dict[str, Any], settings: Settings) -> set[str]:
    """Stored answers derivation would have given anyway.

    Every engagement key used to be copied into a new project record,
    including the ones that were only defaults or were themselves derived.
    That froze them as decisions: the console could no longer tell "someone
    chose this" from "nothing chose this", so it asked for four fields that
    already had answers.
    """
    if not engagement:
        return set()

    # What derivation produces from this project's own repository, with every
    # derivable field cleared so none of them is taken as given.
    probe_values = {
        **undone(settings),
        **{k: v for k, v in engagement.items() if k not in DERIVABLE and v not in (None, "")},
        **{k: Settings.model_fields[k].default for k in DERIVABLE},
    }
    probe = derive(Settings(**probe_values))

    return {
        key
        for key in DERIVABLE
        if key in engagement
        and _canonical(engagement[key]) == _canonical(getattr(probe, key, None))
    }


def defaults_from(settings: Settings) -> dict[str, Any]:
    """The environment's answers, used to seed a new project.

    A new engagement starts from whatever the deployment was configured with
    rather than from blank fields, because most of them are right most of the
    time and the ones that are not are obvious.

    Only what was actually answered. Storing a derived or default value here
    turns it into something someone appears to have chosen, and the console
    then asks about it forever.
    """
    stored = {key: getattr(settings, key, None) for key in ENGAGEMENT_KEYS}
    for key in settings.derived_keys:
        stored.pop(key, None)
    for key in DERIVABLE:
        if key in stored and stored[key] == Settings.model_fields[key].default:
            stored.pop(key)
    return {k: v for k, v in stored.items() if v not in (None, "")}


async def list_all(include_archived: bool = False) -> list[ProjectRecord]:
    async with get_sessionmaker()() as session:
        rows = (await session.execute(select(Project).order_by(Project.id))).scalars().all()
    return [
        _record(row)
        for row in rows
        if include_archived or not row.archived
    ]


async def get(project_id: str) -> ProjectRecord | None:
    async with get_sessionmaker()() as session:
        row = await session.get(Project, validate_id(project_id))
    return _record(row) if row else None


async def ensure_default(settings: Settings) -> ProjectRecord:
    """The default project exists as a record, not as an absence.

    Without it every consumer has to remember that "default" means "the one
    with no row", and the console has nothing to show on a fresh install.
    """
    existing = await get(DEFAULT_PROJECT)
    if existing:
        return existing
    return await create(
        DEFAULT_PROJECT,
        name="Default",
        description="The engagement this deployment was configured with.",
        engagement=defaults_from(settings),
    )


async def create(
    project_id: str,
    *,
    name: str = "",
    description: str = "",
    engagement: dict[str, Any] | None = None,
) -> ProjectRecord:
    project_id = validate_id(project_id)
    if await get(project_id):
        raise ProjectError(f"project {project_id!r} already exists")

    async with get_sessionmaker()() as session:
        row = Project(
            id=project_id,
            name=name or project_id,
            description=description,
            engagement=_only_known(engagement or {}),
        )
        session.add(row)
        await session.commit()
    return _record(row)


async def update(
    project_id: str,
    *,
    name: str | None = None,
    description: str | None = None,
    engagement: dict[str, Any] | None = None,
) -> ProjectRecord:
    project_id = validate_id(project_id)
    async with get_sessionmaker()() as session:
        row = await session.get(Project, project_id)
        if row is None:
            raise ProjectError(f"no project {project_id!r}")
        if name is not None:
            row.name = name
        if description is not None:
            row.description = description
        if engagement is not None:
            # Merged, not replaced: the console sends the fields it edited,
            # and a partial update must not blank the rest.
            row.engagement = {**(row.engagement or {}), **_only_known(engagement)}
        await session.commit()
        await session.refresh(row)
    return _record(row)


async def archive(project_id: str) -> None:
    """Hide a finished engagement without destroying its trail.

    Deleting would take the runs and audit entries that reference it, and an
    engagement that ended is exactly the one whose record someone will want
    to read later.
    """
    project_id = validate_id(project_id)
    if project_id == DEFAULT_PROJECT:
        raise ProjectError("the default project cannot be archived")
    async with get_sessionmaker()() as session:
        row = await session.get(Project, project_id)
        if row is None:
            raise ProjectError(f"no project {project_id!r}")
        row.archived = True
        await session.commit()


async def delete_forever(project_id: str) -> None:
    """Only for a project created by mistake. Leaves the graph alone —
    purging that is a separate, explicit act."""
    project_id = validate_id(project_id)
    if project_id == DEFAULT_PROJECT:
        raise ProjectError("the default project cannot be deleted")
    async with get_sessionmaker()() as session:
        await session.execute(delete(Project).where(Project.id == project_id))
        await session.commit()


def applied_to(settings: Settings, record: ProjectRecord | None) -> Settings:
    """Settings as they should read while this project is active.

    The project's engagement values overlay the environment's. Anything the
    project does not answer falls through, so a project that only names a
    repository still inherits every other default rather than nulling it.
    """
    if record is None:
        return settings
    overlay = {k: v for k, v in (record.engagement or {}).items() if v not in (None, "")}
    # Values already stored by an older version, or written before this rule
    # existed. Dropped rather than migrated: they say nothing, so honouring
    # them only suppresses the derivation that would say the same thing.
    for key in redundant(overlay, settings):
        overlay.pop(key, None)
    if not overlay:
        return settings
    # model_copy does not re-run validators, so the derived fields would
    # still describe whatever the environment named. Reset them first, then
    # derive: a project that names only a repository should have the rest
    # follow from *its* repository, not from the one before it.
    #
    # Only what derivation itself filled in — `derived_keys` is the record of
    # exactly that. Resetting a fixed list instead discarded values someone
    # had set deliberately, which is the opposite of the point.
    #
    # Reset to the field's own default rather than to None: `target_ref`
    # defaults to "main", and blanking it outright nulls a default that
    # derivation cannot refill when no repository is named.
    blanks = {
        k: v for k, v in undone(settings).items()
        if k in settings.derived_keys and k not in overlay
    }
    return derive(settings.model_copy(update={**blanks, **overlay}))


def _only_known(engagement: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in engagement.items() if k in ENGAGEMENT_KEYS}


def _record(row: Project) -> ProjectRecord:
    return ProjectRecord(
        id=row.id,
        name=row.name,
        description=row.description,
        engagement=dict(row.engagement or {}),
        archived=bool(row.archived),
        created_at=row.created_at.isoformat() if getattr(row, "created_at", None) else None,
    )
