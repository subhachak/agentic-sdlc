"""Which project a node belongs to.

The graph was single-project by construction and silently so. `purge_phase`
removed every edge its phase had ever written, regardless of repository, so
indexing a second repository deleted the first one — no error, no warning,
and the first team's next design phase simply refused against an empty graph.

Scoping is carried in the node's `system` field rather than in a new column,
for two reasons. Node identity is already derived from
`type|system|external_id`, so qualifying the system makes two projects'
identical file paths distinct identities for free — without it they would
collide and each index would overwrite the other's projections. And there is
no migration tooling here, so a column would need one.

The default project is deliberately *unqualified*. A single-project
deployment keeps `system == "code"` and needs no re-index, and a graph
written before this existed is still readable as the default project rather
than being orphaned into a namespace nobody queries.
"""

from __future__ import annotations

import re

DEFAULT_PROJECT = "default"

# Project ids end up in node identity, so they have to be stable and
# unambiguous — `a@b` in a project name would make `code@a@b` unparseable.
_VALID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,62}$")


class ProjectError(ValueError):
    pass


def validate(project: str) -> str:
    candidate = (project or "").strip().lower()
    if candidate == DEFAULT_PROJECT:
        return DEFAULT_PROJECT
    if not _VALID.match(candidate):
        raise ProjectError(
            f"invalid project id {project!r}: lower-case letters, digits, dot, "
            f"dash and underscore only, up to 63 characters"
        )
    return candidate


def scoped(system: str, project: str = DEFAULT_PROJECT) -> str:
    """The system name a node of this project is stored under."""
    project = validate(project)
    return system if project == DEFAULT_PROJECT else f"{system}@{project}"


def project_of(system: str) -> str:
    """Which project a stored system name belongs to.

    An unqualified system is the default project, which is what keeps a graph
    written before projects existed readable rather than stranded.
    """
    _, separator, project = (system or "").partition("@")
    return project if separator else DEFAULT_PROJECT


def base_system(system: str) -> str:
    """The system name without its project qualifier."""
    return (system or "").partition("@")[0]


def sql_pattern(project: str = DEFAULT_PROJECT) -> tuple[str, bool]:
    """A LIKE pattern for one project's systems, and whether to negate it.

    Returned rather than applied so the store owns the query and this module
    owns the naming rule. The default project is every system with no
    qualifier at all, which cannot be expressed as a positive LIKE.
    """
    project = validate(project)
    if project == DEFAULT_PROJECT:
        return "%@%", True      # NOT LIKE: anything unqualified
    return f"%@{project}", False
