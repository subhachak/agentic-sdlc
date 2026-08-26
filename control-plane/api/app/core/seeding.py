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
from app.core.source_kinds import is_test_path
from app.graph.identity import IDENTITY_VERSION
from app.graph.paths import canonical
from app.graph.projects import DEFAULT_PROJECT, scoped
from app.graph.projects import validate as validate_project
from app.ports.code_intelligence import CodeIndex, CodeIntelligence

CODE_SYSTEM = "code"


CODE_INDEX_PHASE = "code-index"


def assertions_from_index(
    index: CodeIndex, project: str = DEFAULT_PROJECT
) -> list[Assertion]:
    prov = index.provenance
    # The project qualifies the system, which is what makes two projects'
    # identical file paths distinct identities rather than one overwriting
    # the other's projections.
    system = scoped(CODE_SYSTEM, project)
    # Carried on every module rather than kept in the seed's return value,
    # because the consumer that needs it — the design review, deciding whether
    # this graph is good enough to derive an impact set from — reads the graph,
    # not the log line from whenever it was last seeded.
    stamp = {
        "commit_sha": prov.commit_sha,
        "indexer_version": prov.indexer_version,
        "indexed_at": prov.indexed_at,
        "internal_capture_rate": prov.internal_capture_rate,
        "most_missed": prov.most_missed[:5],
        # Where the deployable units are. Manifests are not source and are
        # not stored as files, so if this is not carried here nothing can
        # work out what is separately testable after the fact.
        "units": prov.units,
        # Which id scheme these nodes were minted under. Escaping the
        # delimiter changed the derivation, so a graph written before it
        # holds ids this build would not produce — and mixing the two in one
        # store means cross-plane edges pointing at nothing.
        "identity_version": IDENTITY_VERSION,
    }
    metadata = {f.path: f for f in index.files}

    def module(cid: str, **projection: Any) -> NodeSpec:
        return NodeSpec("MODULE", system, cid, projection)

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
        # Canonicalised here too, so an indexed path and an agent-authored
        # path for the same file mint the same node. The indexer's own output
        # is already clean; this is what keeps it comparable with everything
        # else that names a file.
        return NodeSpec("SOURCE_ARTIFACT", system, canonical(path), projection)

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
                # Provenance per edge: derived by static extraction, not
                # observed at runtime or declared by a human. `kind` and
                # `from_test` are what let a consumer ask for runtime product
                # coupling without losing the edges it did not want.
                {
                    "provenance": "static-import",
                    "indexer_version": prov.indexer_version,
                    "kind": imported.kind,
                    "from_test": imported.from_test,
                },
            )
        )

    # One edge per file pair, carrying every route between them. An edge is
    # unique on (type, source, target, run), so emitting one per route would
    # silently keep whichever arrived last — this repository's console calls
    # six endpoints in one router file, which would have become one route and
    # five discarded.
    by_pair: dict[tuple[str, str], list[dict[str, str]]] = {}
    for contract in index.contracts:
        by_pair.setdefault((contract.source, contract.target), []).append(
            {"route": contract.route, "method": contract.method}
        )

    for (source, target), routes in sorted(by_pair.items()):
        assertions.append(
            Assertion(
                "CALLS_ENDPOINT",
                artifact(source),
                artifact(target),
                {
                    "provenance": "static-route-match",
                    "indexer_version": prov.indexer_version,
                    "routes": sorted(routes, key=lambda r: (r["route"], r["method"])),
                    "call_count": len(routes),
                    # An HTTP call is runtime coupling by definition, and a
                    # test calling an endpoint is still a test.
                    "kind": "runtime",
                    "from_test": is_test_path(source),
                },
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
    project: str = DEFAULT_PROJECT,
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
    project = validate_project(project)
    index = await indexer.index(repo, ref)
    assertions = assertions_from_index(index, project)

    removed = await graph.purge_phase(CODE_INDEX_PHASE, project) if rebuild else {}
    written = await graph.ingest(run_id, CODE_INDEX_PHASE, assertions)

    prov = index.provenance
    return {
        "project": project,
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
        "contract_edges": len(index.contracts),
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
                "type_only",
                "from_tests",
                "runtime_product",
                "contract_edges",
                "unmatched_calls",
                "uncalled_routes",
                "internal_capture_rate",
                "most_missed",
            }
        ),
        "skipped_files": prov.skipped_files,
    }


def _edge_keys(assertions: list[Assertion]) -> set[tuple[str, str, str]]:
    return {(a.edge, a.src.external_id, a.dst.external_id) for a in assertions}


async def refresh(
    graph: ContextGraphStore,
    indexer: CodeIntelligence,
    repo: str,
    ref: str = "main",
    run_id: str = "seed",
    project: str = DEFAULT_PROJECT,
) -> dict[str, Any]:
    """Bring the graph up to date, and say what changed.

    A rebuild would produce the same graph. This exists because "the same
    graph" is not the same answer as "these four files appeared, these two
    are gone, eleven edges moved" — and a platform whose graph updates
    invisibly is one nobody can audit. The delta is computed by comparing what
    this phase currently asserts against what the index now supports, so it is
    exact rather than inferred from a diff.

    Note what is *not* incremental: the index itself. The adapter reads the
    whole tree either way, because resolving one file's imports needs to know
    every file that exists — a newly added module changes how an untouched
    file's import resolves. What this avoids is rewriting a graph that mostly
    did not change, and losing the ability to report on the part that did.
    """
    project = validate_project(project)
    index = await indexer.index(repo, ref)
    assertions = assertions_from_index(index, project)

    before = await graph.phase_edges(CODE_INDEX_PHASE, project)
    after = _edge_keys(assertions)

    added = after - before
    removed = before - after

    retracted = await graph.retract(CODE_INDEX_PHASE, removed, project) if removed else {"edges": 0, "nodes": 0}
    written = await graph.ingest(run_id, CODE_INDEX_PHASE, assertions)

    prov = index.provenance
    return {
        "project": project,
        "repo": index.repo,
        "ref": index.ref,
        "commit_sha": prov.commit_sha,
        "pinned": prov.commit_sha is not None,
        "indexer_version": prov.indexer_version,
        "indexed_at": prov.indexed_at,
        "modules": len(index.modules),
        "files": len(index.files),
        "edges_written": written,
        "delta": {
            "edges_added": len(added),
            "edges_removed": retracted["edges"],
            "nodes_removed": retracted["nodes"],
            "unchanged": len(before & after),
            # Named rather than only counted: "eleven edges changed" is a
            # number, "this file no longer imports that one" is a fact someone
            # can act on.
            "added_sample": sorted(f"{e} {s} -> {d}" for e, s, d in added)[:20],
            "removed_sample": sorted(f"{e} {s} -> {d}" for e, s, d in removed)[:20],
        },
        "resolution": prov.model_dump(
            include={
                "total_imports", "resolved", "external_package",
                "unresolved_relative", "unresolved_internal",
                "type_only", "from_tests", "runtime_product",
                "contract_edges", "unmatched_calls", "uncalled_routes",
                "internal_capture_rate", "most_missed",
            }
        ),
        "skipped_files": prov.skipped_files,
    }
