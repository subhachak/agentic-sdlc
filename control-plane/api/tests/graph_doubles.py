"""In-memory context graph for tests.

Deliberately uses the real identity function and the real ontology
validation — only storage is faked. A double that skipped those would let a
test pass on an edge the platform would reject.
"""

from __future__ import annotations

from typing import Any

from app.core.context_graph import Assertion
from app.graph.identity import node_id
from app.graph.ontology import EdgeType, NodeType, validate_edge


class InMemoryContextGraph:
    def __init__(self) -> None:
        self.nodes: dict[str, dict[str, Any]] = {}
        self.edges: list[dict[str, Any]] = []

    def _put(self, spec) -> str:
        nid = node_id(spec.type, spec.system, spec.external_id)
        existing = self.nodes.get(nid, {}).get("projection", {})
        self.nodes[nid] = {
            "id": nid,
            "type": spec.type,
            "system": spec.system,
            "external_id": spec.external_id,
            # Merged, not replaced: an assertion that only names a node must
            # not erase what a richer one established.
            "projection": {**existing, **spec.projection},
        }
        return nid

    async def purge_phase(self, phase: str) -> dict[str, int]:
        doomed = [e for e in self.edges if e.get("phase") == phase]
        touched = {e["src_id"] for e in doomed} | {e["dst_id"] for e in doomed}
        self.edges = [e for e in self.edges if e.get("phase") != phase]
        still = {e["src_id"] for e in self.edges} | {e["dst_id"] for e in self.edges}
        orphans = touched - still
        for nid in orphans:
            self.nodes.pop(nid, None)
        return {"edges": len(doomed), "nodes": len(orphans)}

    async def ingest(self, run_id: str, phase: str, assertions: list[Assertion]) -> int:
        written = 0
        for a in assertions:
            validate_edge(a.edge, a.src.type, a.dst.type)
            src, dst = self._put(a.src), self._put(a.dst)
            key = (a.edge, src, dst, run_id)
            if any((e["type"], e["src_id"], e["dst_id"], e["run_id"]) == key for e in self.edges):
                continue
            self.edges.append(
                {"type": a.edge, "src_id": src, "dst_id": dst,
                 "run_id": run_id, "phase": phase, "attributes": a.attributes}
            )
            written += 1
        return written

    def _forward(self, edge_type: str, ids: set[str]) -> set[str]:
        return {e["dst_id"] for e in self.edges if e["type"] == edge_type and e["src_id"] in ids}

    async def neighbours(self, node_id_: str) -> list[dict[str, Any]]:
        return [e for e in self.edges if node_id_ in (e["src_id"], e["dst_id"])]

    async def untested_criteria(self) -> list[dict[str, Any]]:
        passing = {
            n["id"] for n in self.nodes.values()
            if n["type"] == NodeType.TEST_RUN and n["projection"].get("status") == "passed"
        }
        out = []
        for n in self.nodes.values():
            if n["type"] != NodeType.ACCEPTANCE_CRITERION:
                continue
            runs = self._forward(
                EdgeType.EXERCISED_IN,
                self._forward(EdgeType.IMPLEMENTED_BY, self._forward(EdgeType.VERIFIED_BY, {n["id"]})),
            )
            if not (runs & passing):
                out.append(n)
        return out

    async def trace(self, criterion_id: str) -> dict[str, Any]:
        scenarios = self._forward(EdgeType.VERIFIED_BY, {criterion_id})
        scripts = self._forward(EdgeType.IMPLEMENTED_BY, scenarios)
        runs = self._forward(EdgeType.EXERCISED_IN, scripts)
        render = lambda ids: [self.nodes[i] for i in sorted(ids) if i in self.nodes]  # noqa: E731
        return {
            "criterion": render({criterion_id}),
            "scenarios": render(scenarios),
            "scripts": render(scripts),
            "runs": render(runs),
            "defects": render(self._forward(EdgeType.RAISED, runs)),
        }

    async def blast_radius(self, module_id: str) -> list[dict[str, Any]]:
        dependents = {
            e["src_id"] for e in self.edges
            if e["type"] == EdgeType.DEPENDS_ON and e["dst_id"] == module_id
        }
        targets = dependents | {module_id}
        ids = {e["src_id"] for e in self.edges if e["type"] == EdgeType.COVERS and e["dst_id"] in targets}
        return [self.nodes[i] for i in sorted(ids) if i in self.nodes]

    async def counts(self) -> dict[str, Any]:
        nodes: dict[str, int] = {}
        edges: dict[str, int] = {}
        for n in self.nodes.values():
            nodes[n["type"]] = nodes.get(n["type"], 0) + 1
        for e in self.edges:
            edges[e["type"]] = edges.get(e["type"], 0) + 1
        return {"nodes": nodes, "edges": edges}

    async def module_paths(self) -> dict[str, set[str]]:
        out: dict[str, set[str]] = {}
        for e in self.edges:
            if e["type"] != EdgeType.BELONGS_TO:
                continue
            artifact, module = self.nodes.get(e["src_id"]), self.nodes.get(e["dst_id"])
            if artifact and module:
                out.setdefault(module["external_id"], set()).add(artifact["external_id"])
        return out

    async def criteria(self) -> list[dict[str, Any]]:
        return [
            {"id": n["external_id"], "text": n["projection"].get("text", ""),
             "module": n["projection"].get("module")}
            for n in self.nodes.values()
            if n["type"] == NodeType.ACCEPTANCE_CRITERION
        ]

    async def module_dependents(self) -> dict[str, set[str]]:
        out: dict[str, set[str]] = {}
        for e in self.edges:
            if e["type"] != EdgeType.DEPENDS_ON:
                continue
            src, dst = self.nodes.get(e["src_id"]), self.nodes.get(e["dst_id"])
            if src and dst:
                out.setdefault(dst["external_id"], set()).add(src["external_id"])
        return out

    async def module_catalogue(self) -> list[dict[str, Any]]:
        paths = await self.module_paths()
        dependents = await self.module_dependents()
        return [
            {"id": cid, "files": len(p), "depends_on": [],
             "dependents": sorted(dependents.get(cid, set())),
             "paths": sorted(p), "hubs": []}
            for cid, p in paths.items()
        ]

    async def file_dependents(self) -> dict[str, set[str]]:
        out: dict[str, set[str]] = {}
        for e in self.edges:
            if e["type"] != EdgeType.IMPORTS:
                continue
            src, dst = self.nodes.get(e["src_id"]), self.nodes.get(e["dst_id"])
            if src and dst:
                out.setdefault(dst["external_id"], set()).add(src["external_id"])
        return out
