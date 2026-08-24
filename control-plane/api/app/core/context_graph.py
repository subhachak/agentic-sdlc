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

from sqlalchemy import func, or_, select
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

    async def purge_phase(self, phase: str) -> dict[str, int]: ...

    async def phase_edges(self, phase: str) -> set[tuple[str, str, str]]: ...

    async def retract(self, phase: str, edges: set[tuple[str, str, str]]) -> dict[str, int]: ...

    async def index_provenance(self) -> dict[str, Any]: ...

    async def neighbours(self, node_id: str) -> list[dict[str, Any]]: ...

    async def untested_criteria(self) -> list[dict[str, Any]]: ...

    async def trace(self, criterion_id: str) -> dict[str, Any]: ...

    async def blast_radius(self, module_id: str) -> list[dict[str, Any]]: ...

    async def counts(self) -> dict[str, int]: ...

    async def modules(self) -> list[dict[str, Any]]: ...

    async def module_paths(self) -> dict[str, set[str]]: ...

    async def module_catalogue(self) -> list[dict[str, Any]]: ...

    async def module_dependents(self) -> dict[str, set[str]]: ...

    async def file_dependents(
        self,
        *,
        runtime_only: bool = True,
        include_tests: bool = True,
        include_contracts: bool = True,
    ) -> dict[str, set[str]]: ...

    async def criteria(self) -> list[dict[str, Any]]: ...


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
        module once with its file count and again as the endpoint of a
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

    async def purge_phase(self, phase: str) -> dict[str, int]:
        """Remove everything one phase asserted, and any node left orphaned.

        Derived structure is rebuilt, not migrated. What makes this safe is
        that it is scoped by phase: an edge another phase wrote about the same
        file is an audit record and stays, and so does the node it hangs from.
        A node is only dropped once nothing at all refers to it.
        """
        async with get_sessionmaker()() as session:
            edges = (
                await session.execute(select(GraphEdge).where(GraphEdge.phase == phase))
            ).scalars().all()
            touched = {e.src_id for e in edges} | {e.dst_id for e in edges}
            for edge in edges:
                await session.delete(edge)
            await session.flush()

            still_referenced: set[str] = set()
            if touched:
                rows = (
                    await session.execute(
                        select(GraphEdge.src_id, GraphEdge.dst_id).where(
                            or_(
                                GraphEdge.src_id.in_(touched),
                                GraphEdge.dst_id.in_(touched),
                            )
                        )
                    )
                ).all()
                for src, dst in rows:
                    still_referenced.update((src, dst))

            orphans = touched - still_referenced
            for node_id_ in orphans:
                node = await session.get(GraphNode, node_id_)
                if node is not None:
                    await session.delete(node)

            await session.commit()

        return {"edges": len(edges), "nodes": len(orphans)}

    async def phase_edges(self, phase: str) -> set[tuple[str, str, str]]:
        """What one phase currently asserts, in the terms a caller thinks in.

        Keyed by external ids rather than node ids so a caller can compare
        against freshly derived assertions without resolving them first —
        which is what makes an incremental update a comparison rather than a
        rebuild.
        """
        async with get_sessionmaker()() as session:
            nodes = {
                n.id: n.external_id
                for n in (await session.execute(select(GraphNode))).scalars().all()
            }
            edges = (
                await session.execute(select(GraphEdge).where(GraphEdge.phase == phase))
            ).scalars().all()

        out: set[tuple[str, str, str]] = set()
        for edge in edges:
            src, dst = nodes.get(edge.src_id), nodes.get(edge.dst_id)
            if src and dst:
                out.add((edge.type, src, dst))
        return out

    async def retract(
        self, phase: str, edges: set[tuple[str, str, str]]
    ) -> dict[str, int]:
        """Withdraw specific assertions, and drop whatever they orphan.

        The narrow counterpart to purge_phase. An incremental update removes
        only the edges the new index no longer supports, so an edge another
        phase wrote — and a node that still carries one — survives untouched.
        """
        if not edges:
            return {"edges": 0, "nodes": 0}

        async with get_sessionmaker()() as session:
            nodes = {
                n.id: n.external_id
                for n in (await session.execute(select(GraphNode))).scalars().all()
            }
            stored = (
                await session.execute(select(GraphEdge).where(GraphEdge.phase == phase))
            ).scalars().all()

            doomed = [
                edge
                for edge in stored
                if (edge.type, nodes.get(edge.src_id), nodes.get(edge.dst_id)) in edges
            ]
            touched = {e.src_id for e in doomed} | {e.dst_id for e in doomed}
            for edge in doomed:
                await session.delete(edge)
            await session.flush()

            still: set[str] = set()
            if touched:
                rows = (
                    await session.execute(
                        select(GraphEdge.src_id, GraphEdge.dst_id).where(
                            or_(
                                GraphEdge.src_id.in_(touched),
                                GraphEdge.dst_id.in_(touched),
                            )
                        )
                    )
                ).all()
                for src, dst in rows:
                    still.update((src, dst))

            orphans = touched - still
            for orphan in orphans:
                node = await session.get(GraphNode, orphan)
                if node is not None:
                    await session.delete(node)
            await session.commit()

        return {"edges": len(doomed), "nodes": len(orphans)}

    async def index_provenance(self) -> dict[str, Any]:
        """Which snapshot of the codebase this graph currently holds.

        Every consumer that reads structure — impact, containment, retrieval —
        is reading one commit's worth of it. An answer derived from a graph
        that cannot say which commit it describes is not reproducible, so the
        stamp is queryable rather than buried in seed output nobody kept.
        """
        async with get_sessionmaker()() as session:
            row = (
                await session.execute(
                    select(GraphNode)
                    .where(GraphNode.type == NodeType.MODULE)
                    .limit(1)
                )
            ).scalars().first()

        projection = row.projection if row else {}
        return {
            "repo": projection.get("repo"),
            "commit_sha": projection.get("commit_sha"),
            "indexer_version": projection.get("indexer_version"),
            "indexed_at": projection.get("indexed_at"),
            "pinned": bool(projection.get("commit_sha")),
            "internal_capture_rate": projection.get("internal_capture_rate"),
            "most_missed": projection.get("most_missed") or [],
        }

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

    async def blast_radius(self, module_id: str) -> list[dict[str, Any]]:
        """Scenarios that cover a module, directly or through a dependent.

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
            if e.type == EdgeType.DEPENDS_ON and e.dst_id == module_id
        }
        targets = dependents | {module_id}
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

    async def modules(self) -> list[dict[str, Any]]:
        """Derived modules with their outgoing dependencies, heaviest first."""
        async with get_sessionmaker()() as session:
            nodes = {
                n.id: n
                for n in (
                    await session.execute(
                        select(GraphNode).where(GraphNode.type == NodeType.MODULE)
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

    async def module_paths(self) -> dict[str, set[str]]:
        """Module id to the file paths it owns.

        What the change review needs to decide whether an edit lands inside
        the modules the design named.
        """
        async with get_sessionmaker()() as session:
            nodes = {
                n.id: n for n in (await session.execute(select(GraphNode))).scalars().all()
            }
            edges = (
                await session.execute(
                    select(GraphEdge).where(
                        GraphEdge.type == EdgeType.BELONGS_TO,
                        GraphEdge.superseded_at.is_(None),
                    )
                )
            ).scalars().all()

        out: dict[str, set[str]] = {}
        for edge in edges:
            artifact, module = nodes.get(edge.src_id), nodes.get(edge.dst_id)
            if artifact and module:
                out.setdefault(module.external_id, set()).add(artifact.external_id)
        return out

    async def criteria(self) -> list[dict[str, Any]]:
        async with get_sessionmaker()() as session:
            rows = (
                await session.execute(
                    select(GraphNode).where(GraphNode.type == NodeType.ACCEPTANCE_CRITERION)
                )
            ).scalars().all()
        return [
            {"id": r.external_id, "text": r.projection.get("text", ""),
             "module": r.projection.get("module")}
            for r in rows
        ]

    async def module_catalogue(self) -> list[dict[str, Any]]:
        """What the design agent is allowed to choose from.

        Modules with their dependencies in both directions and a sample of
        their files. An agent given only names guesses at what is inside them;
        an agent given every path drowns.
        """
        modules = await self.modules()
        paths = await self.module_paths()
        dependents = await self.module_dependents()
        # Product coupling only: a module's hubs should describe the
        # product, not which of its files the test suite imports most.
        fan_in = await self.file_dependents(include_tests=False)

        def hubs(module_paths: set[str]) -> list[str]:
            """The files inside a module that most things import.

            A change to one of these is genuinely wide, and an agent choosing
            where to work has no other way to know that.
            """
            ranked = sorted(
                ((len(fan_in.get(p, ())), p) for p in module_paths), reverse=True
            )
            return [f"{p} ({n} importers)" for n, p in ranked[:3] if n > 1]

        return [
            {
                "id": c["id"],
                "files": c["files"],
                "depends_on": [d["target"] for d in c["depends_on"]],
                "dependents": sorted(dependents.get(c["id"], set())),
                "paths": sorted(paths.get(c["id"], set())),
                "hubs": hubs(paths.get(c["id"], set())),
            }
            for c in modules
        ]

    async def module_dependents(self) -> dict[str, set[str]]:
        """Reverse dependency edges: module -> what depends on it.

        The impact set is derived from this rather than proposed, because an
        architect can be wrong about consequences and the edges cannot.
        """
        async with get_sessionmaker()() as session:
            nodes = {
                n.id: n
                for n in (
                    await session.execute(
                        select(GraphNode).where(GraphNode.type == NodeType.MODULE)
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

        out: dict[str, set[str]] = {}
        for edge in edges:
            src, dst = nodes.get(edge.src_id), nodes.get(edge.dst_id)
            if src and dst:
                out.setdefault(dst.external_id, set()).add(src.external_id)
        return out

    async def file_dependents(
        self,
        *,
        runtime_only: bool = True,
        include_tests: bool = True,
        include_contracts: bool = True,
    ) -> dict[str, set[str]]:
        """File to the files that reach it.

        The unit of truth for impact. Rolling this up to modules before
        traversing gives every file in a directory the same blast radius,
        which cannot distinguish a leaf from a hub.

        Filtered by edge kind rather than at index time, because the right
        answer differs per caller. Impact and hub ranking want runtime product
        coupling: a type-only import is erased at compile time, and counting
        test importers ranks a module by how well tested it is. Regression
        scoping wants the test edges specifically — they are how you find
        which tests to run.

        Contract edges are included by default and are the reason a route
        handler's impact set contains its callers at all: they import nothing
        from one another, so on imports alone a change to an API reports no
        frontend impact whatsoever.
        """
        wanted = [EdgeType.IMPORTS]
        if include_contracts:
            wanted.append(EdgeType.CALLS_ENDPOINT)

        async with get_sessionmaker()() as session:
            nodes = {
                n.id: n.external_id
                for n in (
                    await session.execute(
                        select(GraphNode).where(GraphNode.type == NodeType.SOURCE_ARTIFACT)
                    )
                ).scalars().all()
            }
            edges = (
                await session.execute(
                    select(GraphEdge).where(
                        GraphEdge.type.in_(wanted),
                        GraphEdge.superseded_at.is_(None),
                    )
                )
            ).scalars().all()

        out: dict[str, set[str]] = {}
        for edge in edges:
            attributes = edge.attributes or {}
            # An edge written before classification existed carries neither
            # attribute. Reading those as runtime product code keeps an older
            # graph usable rather than silently emptying it.
            if runtime_only and attributes.get("kind", "runtime") != "runtime":
                continue
            if not include_tests and attributes.get("from_test", False):
                continue
            src, dst = nodes.get(edge.src_id), nodes.get(edge.dst_id)
            if src and dst:
                out.setdefault(dst, set()).add(src)
        return out
