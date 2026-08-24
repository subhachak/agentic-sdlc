"""Turn a derived code index into context-graph assertions.

The seeder writes the *code intelligence* half of the graph: which
modules exist, which files belong to them, and what depends on what. It
never writes the traceability half — COVERS, VERIFIED_BY and the rest are
claims about what was tested, and only a run that actually tested something
is entitled to assert those.

Seeding is re-runnable. Node ids are derived from module and file
identity, so re-indexing a repository updates projections rather than
creating a parallel set of nodes.
"""

from __future__ import annotations

from typing import Any

from app.core.context_graph import Assertion, ContextGraphStore, NodeSpec
from app.ports.code_intelligence import CodeIndex, CodeIntelligence

CODE_SYSTEM = "code"


def assertions_from_index(index: CodeIndex) -> list[Assertion]:
    def module(cid: str, **projection: Any) -> NodeSpec:
        return NodeSpec("MODULE", CODE_SYSTEM, cid, projection)

    assertions: list[Assertion] = []

    for comp in index.modules:
        spec = module(comp.id, file_count=len(comp.paths), repo=index.repo, owners=comp.owners)
        for path in comp.paths:
            assertions.append(
                Assertion(
                    "BELONGS_TO",
                    NodeSpec("SOURCE_ARTIFACT", CODE_SYSTEM, path, {"module": comp.id}),
                    spec,
                )
            )

    for imported in index.imports:
        assertions.append(
            Assertion(
                "IMPORTS",
                NodeSpec("SOURCE_ARTIFACT", CODE_SYSTEM, imported.source, {}),
                NodeSpec("SOURCE_ARTIFACT", CODE_SYSTEM, imported.target, {}),
            )
        )

    for dep in index.dependencies:
        assertions.append(
            Assertion(
                "DEPENDS_ON",
                module(dep.source),
                module(dep.target),
                {"weight": dep.weight},
            )
        )

    return assertions


async def seed(
    graph: ContextGraphStore,
    indexer: CodeIntelligence,
    repo: str,
    ref: str = "main",
    run_id: str = "seed",
) -> dict[str, Any]:
    """Index a repository and write its structure into the context graph."""
    index = await indexer.index(repo, ref)
    assertions = assertions_from_index(index)
    written = await graph.ingest(run_id, "code-index", assertions)

    return {
        "repo": index.repo,
        "ref": index.ref,
        "modules": len(index.modules),
        "files": len(index.files),
        "dependencies": len(index.dependencies),
        "file_imports": len(index.imports),
        "edges_written": written,
        "unresolved_imports": index.unresolved_imports,
        "skipped_files": index.skipped_files,
    }
