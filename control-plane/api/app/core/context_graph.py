"""The traceability graph: writes, and the queries that justify it.

Part of the deterministic core. It knows the ontology and the tables; it
knows nothing about Jira, GitHub or any other system of record — resolving a
native identifier into a node is the EntityResolver port's job.

Written by gates, not by a crawler. Every phase already knows the
relationships it creates at the moment its gate decides, so `ingest` is
called with those assertions and stamps each edge with the run that made it.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol

from sqlalchemy import func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.core.db import get_sessionmaker
from app.graph.ontology import EdgeType, NodeType, validate_edge
from app.models.graph import GraphEdge, GraphNode
from app.ports.entity_resolver import EntityResolver, NodeRef


@dataclass
class NodeSpec:
    """A node as an upstream phase describes it, before resolution."""

    type: str
    system: str
    external_id: str
    projection: dict[str, Any] = field(default_factory=dict)


@dataclass
class Assertion:
    """One relationship a phase observed, with the provenance to prove it."""

    edge: str
    src: NodeSpec
    dst: NodeSpec
    attributes: dict[str, Any] = field(default_factory=dict)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ContextGraphStore(Protocol):
    async def ingest(
        self, run_id: str, phase: str, assertions: list[Assertion]
    ) -> int: ...

    async def neighbours(self, node_id: str) -> list[dict[str, Any]]: ...

    async def untested_criteria(self) -> list[dict[str, Any]]: ...

    async def trace(self, criterion_id: str) -> dict[str, Any]: ...

    async def blast_radius(self, component_id: str) -> list[dict[str, Any]]: ...

    async def counts(self) -> dict[str, int]: ...

    async def components(self) -> list[dict[str, Any]]: ...


class SqlContextGraph:
    def __init__(self, resolver: EntityResolver) -> None:
        self._resolver = resolver

    async def _resolve(self, spec: NodeSpec) -> NodeRef:
        return await self._resolver.resolve(
            spec.type, spec.system, spec.external_id, spec.projection
        )

    async def ingest(self, run_id: str, phase: str, assertions: list[Assertion]) -> int:
        """Write nodes and edges for one phase's observations.

        Idempotent twice over: node ids are derived rather than allocated, and
        an edge is unique on (type, src, dst, run). Re-ingesting the same
        result — which the reconciler can do if a resume is retried — changes
        nothing.

        Projections are merged, never replaced. The code seeder names a
        component once with its file count and again as the endpoint of a
        dependency; the second mention must not erase what the first knew.
        """
        if not assertions:
            return 0

        # Resolve every node once, folding together everything the batch knows
        # about it, before touching the database.
        resolved: dict[str, NodeRef] = {}
        for assertion in assertions:
            validate_edge(assertion.edge, assertion.src.type, assertion.dst.type)
            for spec in (assertion.src, assertion.dst):
                ref = await self._resolve(spec)
                existing = resolved.get(ref.id)
                if existing is None:
                    resolved[ref.id] = ref
                else:
                    existing.projection = {**existing.projection, **ref.projection}

        written = 0
        async with get_sessionmaker()() as session:
            for ref in resolved.values():
                stored = await session.get(GraphNode, ref.id)
                merged = {**(stored.projection if stored else {}), **ref.projection}
                await session.execute(
                    sqlite_insert(GraphNode)
                    .values(
                        id=ref.id,
                        type=ref.type,
                        system=ref.system,
                        external_id=ref.external_id,
                        projection=merged,
                        created_at=_now(),
                    )
                    .on_conflict_do_update(
                        index_elements=[GraphNode.id], set_={"projection": merged}
                    )
                )

            for assertion in assertions:
                src = resolved[(await self._resolve(assertion.src)).id]
                dst = resolved[(await self._resolve(assertion.dst)).id]
                result = await session.execute(
                    sqlite_insert(GraphEdge)
                    .values(
                        id=str(uuid.uuid4()),
                        type=assertion.edge,
                        src_id=src.id,
                        dst_id=dst.id,
                        run_id=run_id,
                        phase=phase,
                        attributes=assertion.attributes,
                        created_at=_now(),
                    )
                    .on_conflict_do_nothing(
                        index_elements=[
                            GraphEdge.type, GraphEdge.src_id, GraphEdge.dst_id, GraphEdge.run_id
                        ]
                    )
                )
                written += result.rowcount or 0

            await session.commit()
        return written

    async def neighbours(self, node_id: str) -> list[dict[str, Any]]:
        async with get_sessionmaker()() as session:
            rows = await session.execute(
                select(GraphEdge).where(
                    (GraphEdge.src_id == node_id) | (GraphEdge.dst_id == node_id),
                    GraphEdge.superseded_at.is_(None),
                )
            )
            return [
                {
                    "type": e.type,
                    "src_id": e.src_id,
                    "dst_id": e.dst_id,
                    "run_id": e.run_id,
                    "phase": e.phase,
                }
                for e in rows.scalars().all()
            ]

    async def untested_criteria(self) -> list[dict[str, Any]]:
        """Acceptance criteria with no scenario that reached a passing run.

        This is the query release readiness is gated on, and the reason the
        graph is foundational rather than an enhancement: it is not derivable
        from a run log.
        """
        async with get_sessionmaker()() as session:
            criteria = (
                await session.execute(
                    select(GraphNode).where(GraphNode.type == NodeType.ACCEPTANCE_CRITERION)
                )
            ).scalars().all()

            # Walk criterion -> scenario -> script -> run, and keep only the
            # criteria whose chain reaches a run that passed.
            edges = (
                await session.execute(
                    select(GraphEdge).where(GraphEdge.superseded_at.is_(None))
                )
            ).scalars().all()

            by_type: dict[str, list[GraphEdge]] = {}
            for e in edges:
                by_type.setdefault(e.type, []).append(e)

            def forward(edge_type: str, ids: set[str]) -> set[str]:
                return {e.dst_id for e in by_type.get(edge_type, []) if e.src_id in ids}

            passing_runs = {
                n.id
                for n in (
                    await session.execute(
                        select(GraphNode).where(GraphNode.type == NodeType.TEST_RUN)
                    )
                ).scalars().all()
                if n.projection.get("status") == "passed"
            }

            covered: set[str] = set()
            for criterion in criteria:
                scenarios = forward(EdgeType.VERIFIED_BY, {criterion.id})
                scripts = forward(EdgeType.IMPLEMENTED_BY, scenarios)
                runs = forward(EdgeType.EXERCISED_IN, scripts)
                if runs & passing_runs:
                    covered.add(criterion.id)

            return [
                {"id": c.id, "external_id": c.external_id, "projection": c.projection}
                for c in criteria
                if c.id not in covered
            ]

    async def trace(self, criterion_id: str) -> dict[str, Any]:
        """Everything reachable from one criterion, one hop at a time."""
        async with get_sessionmaker()() as session:
            edges = (
                await session.execute(
                    select(GraphEdge).where(GraphEdge.superseded_at.is_(None))
                )
            ).scalars().all()
            nodes = {
                n.id: n
                for n in (await session.execute(select(GraphNode))).scalars().all()
            }

        def hop(edge_type: str, ids: set[str]) -> set[str]:
            return {e.dst_id for e in edges if e.type == edge_type and e.src_id in ids}

        scenarios = hop(EdgeType.VERIFIED_BY, {criterion_id})
        scripts = hop(EdgeType.IMPLEMENTED_BY, scenarios)
        runs = hop(EdgeType.EXERCISED_IN, scripts)
        defects = hop(EdgeType.RAISED, runs)

        def render(ids: set[str]) -> list[dict[str, Any]]:
            return [
                {"id": i, "external_id": nodes[i].external_id, "projection": nodes[i].projection}
                for i in sorted(ids)
                if i in nodes
            ]

        return {
            "criterion": render({criterion_id}),
            "scenarios": render(scenarios),
            "scripts": render(scripts),
            "runs": render(runs),
            "defects": render(defects),
        }

    async def blast_radius(self, component_id: str) -> list[dict[str, Any]]:
        """Scenarios that cover a component, directly or through a dependent.

        Two hops is deliberate: it is what the code intelligence graph can
        support honestly today, and unbounded traversal is the query that
        would justify moving to a graph store.
        """
        async with get_sessionmaker()() as session:
            edges = (
                await session.execute(
                    select(GraphEdge).where(GraphEdge.superseded_at.is_(None))
                )
            ).scalars().all()
            nodes = {
                n.id: n
                for n in (await session.execute(select(GraphNode))).scalars().all()
            }

        dependents = {
            e.src_id for e in edges
            if e.type == EdgeType.DEPENDS_ON and e.dst_id == component_id
        }
        targets = dependents | {component_id}
        scenario_ids = {
            e.src_id for e in edges if e.type == EdgeType.COVERS and e.dst_id in targets
        }
        return [
            {"id": i, "external_id": nodes[i].external_id, "projection": nodes[i].projection}
            for i in sorted(scenario_ids)
            if i in nodes
        ]

    async def counts(self) -> dict[str, int]:
        async with get_sessionmaker()() as session:
            nodes = (
                await session.execute(
                    select(GraphNode.type, func.count()).group_by(GraphNode.type)
                )
            ).all()
            edges = (
                await session.execute(
                    select(GraphEdge.type, func.count()).group_by(GraphEdge.type)
                )
            ).all()
        return {
            "nodes": {t: c for t, c in nodes},
            "edges": {t: c for t, c in edges},
        }

    async def components(self) -> list[dict[str, Any]]:
        """Derived components with their outgoing dependencies, heaviest first."""
        async with get_sessionmaker()() as session:
            nodes = {
                n.id: n
                for n in (
                    await session.execute(
                        select(GraphNode).where(GraphNode.type == NodeType.COMPONENT)
                    )
                ).scalars().all()
            }
            edges = (
                await session.execute(
                    select(GraphEdge).where(
                        GraphEdge.type == EdgeType.DEPENDS_ON,
                        GraphEdge.superseded_at.is_(None),
                    )
                )
            ).scalars().all()

        out = []
        for node in nodes.values():
            deps = [
                {
                    "target": nodes[e.dst_id].external_id,
                    "weight": (e.attributes or {}).get("weight", 1),
                }
                for e in edges
                if e.src_id == node.id and e.dst_id in nodes
            ]
            out.append(
                {
                    "id": node.external_id,
                    "files": node.projection.get("file_count", 0),
                    "depends_on": sorted(deps, key=lambda d: -d["weight"]),
                }
            )
        return sorted(out, key=lambda c: -c["files"])
