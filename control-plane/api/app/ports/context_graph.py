"""Port: the context graph.

The platform's central abstraction, and for a long time the only one that
did not live here — it sat in app/core beside the SQLAlchemy implementation,
which is why nothing noticed it had no factory and could not be swapped.

The storage engine is not the architecture. A client may hold this in
Postgres, in Neo4j, or in a hosted graph service; what the platform depends
on is the versioned semantic model below, not where the rows are. Path
queries and indexing strategy belong to the implementation.
"""

from __future__ import annotations

from typing import Any, NotRequired, Protocol, TypedDict

from app.graph.projects import DEFAULT_PROJECT

# ── what these methods return ─────────────────────────────────────────────
#
# TypedDict rather than a model, deliberately. The implementations return
# plain dicts and every consumer indexes them, so models would be a rewrite
# of both sides to state something a type can say for free.
#
# Stating it at all is the point. These were `list[dict[str, Any]]`, so the
# shape lived in whatever consumers happened to read — and the two
# implementations diverged exactly there: production's `modules()` returned
# `files` while the in-memory one returned `name`, so a caller reading
# m["files"] worked against the database and raised KeyError against the
# double. A client bringing PostgreSQL or Neo4j had nothing to build to.


class ModuleSummary(TypedDict):
    """One derived module, heaviest first by file count."""

    id: str
    files: int
    depends_on: list[dict[str, Any]]  # {target, weight}


class ModuleEntry(ModuleSummary):
    """A module with everything the design catalogue needs."""

    dependents: list[str]
    paths: list[str]
    hubs: list[str]


class CriterionRef(TypedDict):
    """An acceptance criterion, as the phases refer to it."""

    id: str
    text: str
    module: NotRequired[str | None]


class UntestedCriterion(TypedDict):
    """A criterion no passing run reaches, and why not."""

    id: str
    external_id: str
    projection: dict[str, Any]
    # "untested" or "stale". Never tested and tested-then-rewritten are
    # different release conversations, so they are not collapsed.
    reason: str


class EdgeRef(TypedDict):
    """One relationship, as a neighbour query returns it."""

    type: str
    src_id: str
    dst_id: str
    run_id: str
    phase: str


class IndexProvenance(TypedDict, total=False):
    """Which snapshot of the codebase the graph currently holds."""

    repo: str | None
    ref: str | None
    commit_sha: str | None
    indexer_version: str
    indexed_at: str
    pinned: bool
    internal_capture_rate: float | None
    most_missed: list[Any]
    units: list[str]
    identity_version: int


class ContextGraphStore(Protocol):
    async def ingest(
        self, run_id: str, phase: str, assertions: list[Assertion]
    ) -> int: ...

    async def purge_phase(self, phase: str) -> dict[str, int]: ...

    async def phase_edges(
        self, phase: str, project: str = DEFAULT_PROJECT
    ) -> set[tuple[str, str, str]]: ...

    async def retract(
        self, phase: str, edges: set[tuple[str, str, str]], project: str = DEFAULT_PROJECT
    ) -> dict[str, int]: ...

    async def retract_run(
        self, run_id: str, phase: str, project: str = DEFAULT_PROJECT
    ) -> dict[str, int]: ...
    """Withdraw everything one run asserted in one phase.

    Distinct from `retract`, which matches edge tuples within a phase and so
    cannot tell two runs apart: edges are unique per run, and two releases
    of the same file are two assertions that happen to look identical.
    Rolling back one run by tuple would withdraw the other's as well."""

    async def index_provenance(self, project: str = DEFAULT_PROJECT) -> IndexProvenance: ...

    async def neighbours(self, node_id: str) -> list[EdgeRef]: ...

    async def untested_criteria(
        self, project: str = DEFAULT_PROJECT, at_revision: str | None = None
    ) -> list[UntestedCriterion]: ...

    async def trace(
        self, criterion_id: str, project: str = DEFAULT_PROJECT
    ) -> dict[str, Any]: ...

    async def blast_radius(
        self, module_id: str, project: str = DEFAULT_PROJECT
    ) -> list[dict[str, Any]]: ...

    async def counts(self, project: str = DEFAULT_PROJECT) -> dict[str, int]: ...

    async def modules(self, project: str = DEFAULT_PROJECT) -> list[ModuleSummary]: ...

    async def module_paths(self, project: str = DEFAULT_PROJECT) -> dict[str, set[str]]: ...

    async def module_catalogue(self, project: str = DEFAULT_PROJECT) -> list[ModuleEntry]: ...

    async def module_dependents(self, project: str = DEFAULT_PROJECT) -> dict[str, set[str]]: ...

    async def file_dependents(
        self,
        project: str = DEFAULT_PROJECT,
        *,
        runtime_only: bool = True,
        include_tests: bool = True,
        include_contracts: bool = True,
    ) -> dict[str, set[str]]: ...

    async def criteria(self, project: str = DEFAULT_PROJECT) -> list[CriterionRef]: ...
