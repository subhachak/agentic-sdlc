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


CODE_INDEX_PHASE = "code-index"


def assertions_from_index(index: CodeIndex) -> list[Assertion]:
    prov = index.provenance
    stamp = {
        "commit_sha": prov.commit_sha,
        "indexer_version": prov.indexer_version,
        "indexed_at": prov.indexed_at,
    }
    metadata = {f.path: f for f in index.files}

    def module(cid: str, **projection: Any) -> NodeSpec:
        return NodeSpec("MODULE", CODE_SYSTEM, cid, projection)

    def artifact(path: str, **extra: Any) -> NodeSpec:
        """A file node carrying what is true of the file itself.

        Hydrated rather than bare: language, content hash, size and exported
        surface travel with the node, so a consumer can ask what a file offers
        without re-reading the repository, and a later index can tell which
        files actually changed.
        """
        meta = metadata.get(path)
        projection: dict[str, Any] = dict(extra)
        if meta:
            projection.update(
                language=meta.language,
                sha256=meta.sha256,
                loc=meta.loc,
                exports=meta.exports,
            )
        return NodeSpec("SOURCE_ARTIFACT", CODE_SYSTEM, path, projection)

    assertions: list[Assertion] = []

    for comp in index.modules:
        spec = module(
            comp.id,
            file_count=len(comp.paths),
            repo=index.repo,
            owners=comp.owners,
            **stamp,
        )
        for path in comp.paths:
            assertions.append(
                Assertion("BELONGS_TO", artifact(path, module=comp.id), spec)
            )

    for imported in index.imports:
        assertions.append(
            Assertion(
                "IMPORTS",
                artifact(imported.source),
                artifact(imported.target),
                # Provenance per edge: this one was derived by regex
                # extraction, not observed at runtime or declared by a human.
                {"provenance": "static-import", "indexer_version": prov.indexer_version},
            )
        )

    for dep in index.dependencies:
        assertions.append(
            Assertion(
                "DEPENDS_ON",
                module(dep.source),
                module(dep.target),
                {"weight": dep.weight, "provenance": "static-import-rollup"},
            )
        )

    return assertions


async def seed(
    graph: ContextGraphStore,
    indexer: CodeIntelligence,
    repo: str,
    ref: str = "main",
    run_id: str = "seed",
    rebuild: bool = True,
) -> dict[str, Any]:
    """Index a repository and write its structure into the context graph.

    Rebuilds by default. The code-intelligence graph is derived and
    disposable — that is the whole reason it is separated from the
    traceability graph — so re-deriving it is cheaper and safer than
    migrating it. Node identity includes the node's type, so a renamed type
    would otherwise leave the old nodes stranded beside the new ones rather
    than being updated in place.

    Only what this phase wrote is removed. Edges another phase asserted about
    a file, and the nodes carrying them, survive: those are audit records, not
    derived structure.
    """
    index = await indexer.index(repo, ref)
    assertions = assertions_from_index(index)

    removed = await graph.purge_phase(CODE_INDEX_PHASE) if rebuild else {}
    written = await graph.ingest(run_id, CODE_INDEX_PHASE, assertions)

    prov = index.provenance
    return {
        "repo": index.repo,
        "ref": index.ref,
        "commit_sha": prov.commit_sha,
        "pinned": prov.commit_sha is not None,
        "indexer_version": prov.indexer_version,
        "indexed_at": prov.indexed_at,
        "modules": len(index.modules),
        "files": len(index.files),
        "dependencies": len(index.dependencies),
        "file_imports": len(index.imports),
        "edges_written": written,
        "rebuilt": bool(rebuild),
        "removed": removed,
        "resolution": prov.model_dump(
            include={
                "total_imports",
                "resolved",
                "external_package",
                "unresolved_relative",
                "unresolved_internal",
                "internal_capture_rate",
                "most_missed",
            }
        ),
        "skipped_files": prov.skipped_files,
    }
