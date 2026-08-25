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

from typing import Any, Protocol

from app.graph.projects import DEFAULT_PROJECT

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

    async def index_provenance(self, project: str = DEFAULT_PROJECT) -> dict[str, Any]: ...

    async def neighbours(self, node_id: str) -> list[dict[str, Any]]: ...

    async def untested_criteria(self, project: str = DEFAULT_PROJECT) -> list[dict[str, Any]]: ...

    async def trace(
        self, criterion_id: str, project: str = DEFAULT_PROJECT
    ) -> dict[str, Any]: ...

    async def blast_radius(
        self, module_id: str, project: str = DEFAULT_PROJECT
    ) -> list[dict[str, Any]]: ...

    async def counts(self, project: str = DEFAULT_PROJECT) -> dict[str, int]: ...

    async def modules(self, project: str = DEFAULT_PROJECT) -> list[dict[str, Any]]: ...

    async def module_paths(self, project: str = DEFAULT_PROJECT) -> dict[str, set[str]]: ...

    async def module_catalogue(self, project: str = DEFAULT_PROJECT) -> list[dict[str, Any]]: ...

    async def module_dependents(self, project: str = DEFAULT_PROJECT) -> dict[str, set[str]]: ...

    async def file_dependents(
        self,
        project: str = DEFAULT_PROJECT,
        *,
        runtime_only: bool = True,
        include_tests: bool = True,
        include_contracts: bool = True,
    ) -> dict[str, set[str]]: ...

    async def criteria(self, project: str = DEFAULT_PROJECT) -> list[dict[str, Any]]: ...
