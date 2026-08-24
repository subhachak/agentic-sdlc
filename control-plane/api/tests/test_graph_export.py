"""Exporting the derived graph for the execution plane.

Two planes, one graph. The execution plane runs in client CI with no route to
this database, which is why it held its own hand-authored copy — free to
disagree, and it did: every coverage claim in that file named a script that
did not exist, and its paths were relative to a directory the other plane
never used. A generated export removes the second source of truth without
pretending the two processes can share a database.
"""

from __future__ import annotations

import pytest

from app.core.context_graph import Assertion, NodeSpec
from app.core.graph_export import build_export
from tests.graph_doubles import InMemoryContextGraph


async def _graph() -> InMemoryContextGraph:
    graph = InMemoryContextGraph()

    def belongs(path: str, module: str) -> Assertion:
        return Assertion(
            "BELONGS_TO",
            NodeSpec("SOURCE_ARTIFACT", "code", path, {}),
            NodeSpec("MODULE", "code", module,
                     {"repo": "acme/thing", "commit_sha": "a" * 40,
                      "indexer_version": "2.0.0", "internal_capture_rate": 0.99}),
        )

    def imports(source: str, target: str, **attrs) -> Assertion:
        return Assertion(
            "IMPORTS",
            NodeSpec("SOURCE_ARTIFACT", "code", source, {}),
            NodeSpec("SOURCE_ARTIFACT", "code", target, {}),
            {"kind": "runtime", "from_test": False, **attrs},
        )

    await graph.ingest("seed", "code-index", [
        belongs("demo-app/app/claims/page.tsx", "demo-app/app/claims"),
        belongs("demo-app/app/api/claims/route.ts", "demo-app/app/api/claims"),
        belongs("control-plane/api/app/main.py", "control-plane/api/app"),
        imports("demo-app/app/claims/page.tsx", "demo-app/app/api/claims/route.ts"),
        imports("control-plane/api/app/main.py", "demo-app/app/api/claims/route.ts"),
    ])
    return graph


@pytest.mark.asyncio
async def test_the_export_carries_the_commit_it_describes():
    """Without it a consumer cannot tell a current graph from one that
    describes a commit it is not testing."""
    export = await build_export(await _graph())

    assert export["generated"] is True
    assert export["provenance"]["commit_sha"] == "a" * 40
    assert export["provenance"]["pinned"] is True


@pytest.mark.asyncio
async def test_scoping_excludes_what_the_consumer_neither_deploys_nor_tests():
    """More than a size question: a QA run testing demo-app should not be told
    that a change reaches the control plane's own modules."""
    export = await build_export(await _graph(), scope="demo-app")

    assert [m["id"] for m in export["modules"]] == [
        "demo-app/app/api/claims",
        "demo-app/app/claims",
    ]
    for sources in export["file_dependents"].values():
        assert all(s.startswith("demo-app/") for s in sources)


@pytest.mark.asyncio
async def test_module_dependencies_are_rederived_from_the_file_edges():
    """Rolled up here rather than read from DEPENDS_ON, so the export cannot
    disagree with the file-level truth it came from."""
    export = await build_export(await _graph(), scope="demo-app")

    assert export["depends_on"] == [
        {"from": "demo-app/app/claims", "to": "demo-app/app/api/claims", "weight": 1}
    ]


@pytest.mark.asyncio
async def test_an_http_call_becomes_a_dependency_the_qa_plane_can_see():
    """The edge the hand-authored file asserted by hand. A page calling a
    route imports nothing from it, so without contract edges the export would
    say the two are unrelated."""
    graph = InMemoryContextGraph()
    await graph.ingest("seed", "code-index", [
        Assertion("BELONGS_TO",
                  NodeSpec("SOURCE_ARTIFACT", "code", "demo-app/app/claims/page.tsx", {}),
                  NodeSpec("MODULE", "code", "demo-app/app/claims", {"commit_sha": "b" * 40})),
        Assertion("BELONGS_TO",
                  NodeSpec("SOURCE_ARTIFACT", "code", "demo-app/app/api/claims/route.ts", {}),
                  NodeSpec("MODULE", "code", "demo-app/app/api/claims", {"commit_sha": "b" * 40})),
        Assertion("CALLS_ENDPOINT",
                  NodeSpec("SOURCE_ARTIFACT", "code", "demo-app/app/claims/page.tsx", {}),
                  NodeSpec("SOURCE_ARTIFACT", "code", "demo-app/app/api/claims/route.ts", {}),
                  {"kind": "runtime", "from_test": False, "route": "/api/claims"}),
    ])

    export = await build_export(graph, scope="demo-app")

    assert export["depends_on"] == [
        {"from": "demo-app/app/claims", "to": "demo-app/app/api/claims", "weight": 1}
    ]


@pytest.mark.asyncio
async def test_test_files_do_not_become_module_dependencies_in_the_export():
    graph = await _graph()
    await graph.ingest("seed", "code-index", [
        Assertion("BELONGS_TO",
                  NodeSpec("SOURCE_ARTIFACT", "code", "demo-app/tests/claims.spec.ts", {}),
                  NodeSpec("MODULE", "code", "demo-app/tests", {"commit_sha": "a" * 40})),
        Assertion("IMPORTS",
                  NodeSpec("SOURCE_ARTIFACT", "code", "demo-app/tests/claims.spec.ts", {}),
                  NodeSpec("SOURCE_ARTIFACT", "code", "demo-app/app/claims/page.tsx", {}),
                  {"kind": "runtime", "from_test": True}),
    ])

    export = await build_export(graph, scope="demo-app")

    assert not any(edge["from"] == "demo-app/tests" for edge in export["depends_on"])


@pytest.mark.asyncio
async def test_an_empty_graph_exports_nothing_rather_than_a_plausible_shape():
    export = await build_export(InMemoryContextGraph(), scope="demo-app")

    assert export["modules"] == []
    assert export["provenance"]["pinned"] is False
