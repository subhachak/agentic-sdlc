"""First-time setup, and every update after it.

Setup used to be one "seed graph" button and an assumption. Everything
downstream depends on the graph being hydrated, and each consumer degrades
differently when it is not: an empty graph refuses, a stale one answers
confidently about the wrong commit, an unbuilt retrieval index grounds an
agent in nothing without saying so. These pin the reporting that replaced
the assumption, and the incremental update that keeps it true.
"""

from __future__ import annotations

import json

import pytest

from app.core import hydration
from app.core.context_graph import Assertion, NodeSpec
from app.core.seeding import refresh, seed
from app.ports.code_intelligence import (
    CodeDependency,
    CodeFile,
    CodeIndex,
    CodeModule,
    FileImport,
    IndexProvenance,
)
from tests.graph_doubles import InMemoryContextGraph


def _index(files: list[str], imports: list[tuple[str, str]], commit: str = "a" * 40) -> CodeIndex:
    modules: dict[str, list[str]] = {}
    for path in files:
        modules.setdefault("/".join(path.split("/")[:-1]), []).append(path)
    return CodeIndex(
        repo="acme/thing",
        ref="main",
        modules=[CodeModule(id=m, paths=sorted(p)) for m, p in sorted(modules.items())],
        files=[CodeFile(path=p, module="/".join(p.split("/")[:-1]), language="python")
               for p in sorted(files)],
        dependencies=[CodeDependency(source="a", target="b", weight=1)] if imports else [],
        imports=[FileImport(source=s, target=t) for s, t in imports],
        provenance=IndexProvenance(commit_sha=commit, indexer_version="test",
                                   internal_capture_rate=0.99, files_indexed=len(files)),
    )


class _Indexer:
    def __init__(self, index: CodeIndex) -> None:
        self.index_value = index

    async def index(self, repo: str, ref: str = "main") -> CodeIndex:
        return self.index_value


# --- incremental update ----------------------------------------------------


@pytest.mark.asyncio
async def test_a_refresh_that_changes_nothing_says_so():
    """The answer people most need and are least often given. "Already
    current" is different from "rebuilt successfully"."""
    graph = InMemoryContextGraph()
    indexer = _Indexer(_index(["app/a.py", "app/b.py"], [("app/a.py", "app/b.py")]))

    await seed(graph, indexer, repo="acme/thing")
    result = await refresh(graph, indexer, repo="acme/thing")

    assert result["delta"]["edges_added"] == 0
    assert result["delta"]["edges_removed"] == 0
    assert result["delta"]["unchanged"] > 0


@pytest.mark.asyncio
async def test_a_new_file_is_reported_as_added_not_as_a_rebuild():
    graph = InMemoryContextGraph()
    before = _Indexer(_index(["app/a.py"], []))
    await seed(graph, before, repo="acme/thing")

    after = _Indexer(_index(["app/a.py", "app/c.py"], [("app/c.py", "app/a.py")]))
    result = await refresh(graph, after, repo="acme/thing")

    assert result["delta"]["edges_added"] >= 2   # the new file's BELONGS_TO and its import
    assert result["delta"]["edges_removed"] == 0
    assert any("app/c.py" in line for line in result["delta"]["added_sample"])


@pytest.mark.asyncio
async def test_a_deleted_file_is_withdrawn_and_named():
    graph = InMemoryContextGraph()
    await seed(graph, _Indexer(_index(["app/a.py", "app/b.py"],
                                      [("app/a.py", "app/b.py")])), repo="acme/thing")

    result = await refresh(graph, _Indexer(_index(["app/a.py"], [])), repo="acme/thing")

    assert result["delta"]["edges_removed"] >= 2
    assert any("app/b.py" in line for line in result["delta"]["removed_sample"])
    assert not any(
        n["external_id"] == "app/b.py" for n in graph.nodes.values()
    )


@pytest.mark.asyncio
async def test_a_refresh_leaves_another_phase_alone():
    """The reason this is a retraction rather than a purge: an edge a run
    asserted about a file is an audit record, and re-reading the repository
    is not grounds to withdraw it."""
    graph = InMemoryContextGraph()
    await seed(graph, _Indexer(_index(["app/a.py", "app/b.py"],
                                      [("app/a.py", "app/b.py")])), repo="acme/thing")
    await graph.ingest("run-1", "release", [
        Assertion("CONTAINS",
                  NodeSpec("RELEASE", "cd", "r-1", {}),
                  NodeSpec("SOURCE_ARTIFACT", "code", "app/b.py", {})),
    ])

    await refresh(graph, _Indexer(_index(["app/a.py"], [])), repo="acme/thing")

    assert [e for e in graph.edges if e["type"] == "CONTAINS"]
    assert any(n["external_id"] == "app/b.py" for n in graph.nodes.values())


@pytest.mark.asyncio
async def test_a_refresh_reports_the_commit_it_moved_to():
    graph = InMemoryContextGraph()
    await seed(graph, _Indexer(_index(["app/a.py"], [], commit="a" * 40)), repo="acme/thing")

    result = await refresh(graph, _Indexer(_index(["app/a.py"], [], commit="b" * 40)),
                           repo="acme/thing")

    assert result["commit_sha"] == "b" * 40
    assert (await graph.index_provenance())["commit_sha"] == "b" * 40


# --- what is hydrated ------------------------------------------------------


class _Retrieval:
    def __init__(self, built: bool, stale: bool = False) -> None:
        self._built, self._stale = built, stale

    async def status(self):
        return {"built": self._built, "chunks": 12 if self._built else 0, "stale": self._stale}


@pytest.mark.asyncio
async def test_an_empty_graph_reports_what_it_blocks(tmp_path):
    status = await hydration.status(InMemoryContextGraph(), _Retrieval(False), tmp_path / "x.json")

    assert status["hydrated"] is False
    index_step = next(s for s in status["steps"] if s["id"] == "index")
    assert index_step["ready"] is False
    assert "refuses" in index_step["detail"]
    # Downstream steps say what they are waiting for rather than just failing.
    assert all(
        s["blocked_by"] == "index" for s in status["steps"] if s["id"] != "index"
    )


@pytest.mark.asyncio
async def test_an_index_that_resolved_too_little_is_flagged_before_a_run_starts(tmp_path):
    """The design phase refuses below 80%. The console should say so before
    someone starts a run and watches it decline."""
    graph = InMemoryContextGraph()
    await seed(graph, _Indexer(_index(["app/a.py"], [])), repo="acme/thing")
    for node in graph.nodes.values():
        if node["type"] == "MODULE":
            node["projection"]["internal_capture_rate"] = 0.55

    status = await hydration.status(graph, _Retrieval(True), tmp_path / "x.json")
    quality = next(s for s in status["steps"] if s["id"] == "index")["quality"]

    assert quality["sufficient"] is False
    assert quality["internal_capture_rate"] == 0.55


@pytest.mark.asyncio
async def test_an_export_describing_another_commit_is_not_ready(tmp_path):
    """A QA run reading it would scope against the wrong commit — which is
    exactly the failure that made a passing result meaningless."""
    graph = InMemoryContextGraph()
    await seed(graph, _Indexer(_index(["app/a.py"], [], commit="b" * 40)), repo="acme/thing")

    export = tmp_path / "code-graph.json"
    export.write_text(json.dumps({
        "generated": True, "modules": [{"id": "m", "paths": []}],
        "provenance": {"commit_sha": "a" * 40},
    }))

    status = await hydration.status(graph, _Retrieval(True), export)
    step = next(s for s in status["steps"] if s["id"] == "export")

    assert step["ready"] is False
    assert "wrong commit" in step["detail"]


@pytest.mark.asyncio
async def test_a_hand_written_export_is_not_accepted_as_generated(tmp_path):
    graph = InMemoryContextGraph()
    await seed(graph, _Indexer(_index(["app/a.py"], [])), repo="acme/thing")
    export = tmp_path / "code-graph.json"
    export.write_text(json.dumps({"modules": [{"id": "m"}]}))

    status = await hydration.status(graph, _Retrieval(True), export)
    step = next(s for s in status["steps"] if s["id"] == "export")

    assert step["ready"] is False
    assert "not generated" in step["detail"]


@pytest.mark.asyncio
async def test_a_stale_retrieval_index_is_not_ready(tmp_path):
    graph = InMemoryContextGraph()
    await seed(graph, _Indexer(_index(["app/a.py"], [])), repo="acme/thing")

    status = await hydration.status(graph, _Retrieval(True, stale=True), tmp_path / "x.json")
    step = next(s for s in status["steps"] if s["id"] == "retrieval")

    assert step["ready"] is False
    assert "stale" in step["detail"]


@pytest.mark.asyncio
async def test_everything_populated_reports_hydrated(tmp_path):
    graph = InMemoryContextGraph()
    await seed(graph, _Indexer(_index(["app/a.py", "app/b.py"],
                                      [("app/a.py", "app/b.py")], commit="c" * 40)),
               repo="acme/thing")
    export = tmp_path / "code-graph.json"
    export.write_text(json.dumps({
        "generated": True, "modules": [{"id": "app", "paths": []}],
        "provenance": {"commit_sha": "c" * 40},
    }))

    status = await hydration.status(graph, _Retrieval(True), export)

    assert status["hydrated"] is True


# --- staying current without being asked -----------------------------------


@pytest.mark.asyncio
async def test_a_release_brings_the_graph_up_to_the_commit_it_shipped():
    """The run just changed the codebase, so the graph describes the commit
    before it. Waiting for someone to remember to re-index is how a design
    phase ends up reasoning about code that no longer exists."""
    from app.agents.nodes import build_nodes
    from app.core.audit import AuditLogger
    from app.core.gate_controller import GateController
    from tests.dispatch_doubles import InMemoryDispatchStore, StubWorkDispatch
    from tests.graph_doubles import InMemoryContextGraph
    from tests.implementation_doubles import StubSourceControl, WritingLLMProvider
    from tests.test_graph_runtime import (
        InMemoryAuditSink,
        StubBuildDeploy,
        StubCodeDesignContext,
        StubRequirementsSource,
        StubTestManagement,
    )

    graph = InMemoryContextGraph()
    indexer = _Indexer(_index(["demo-app/app/claims/page.tsx"], [], commit="d" * 40))
    await seed(graph, indexer, repo="acme/thing")

    logger = AuditLogger(InMemoryAuditSink())
    nodes = build_nodes(
        requirements_source=StubRequirementsSource(),
        code_design_context=StubCodeDesignContext(),
        test_management=StubTestManagement(),
        build_deploy=StubBuildDeploy(),
        work_dispatch=StubWorkDispatch(),
        dispatch_store=InMemoryDispatchStore(),
        context_graph=graph,
        llm_provider=WritingLLMProvider(),
        source_control=StubSourceControl(),
        code_intelligence=_Indexer(
            _index(["demo-app/app/claims/page.tsx", "demo-app/app/claims/Filter.tsx"],
                   [("demo-app/app/claims/Filter.tsx", "demo-app/app/claims/page.tsx")],
                   commit="e" * 40)
        ),
        audit_logger=logger,
        gate_controller=GateController(logger),
        target_repo="acme/thing",
        max_retries=1,
    )

    result = await nodes["release"]({
        "run_id": "run-1",
        "implementation": {"branch": "agentic/run-1", "files": ["demo-app/app/claims/Filter.tsx"]},
    })

    assert result["graph_update"]["commit_sha"] == "e" * 40
    assert result["graph_update"]["edges_added"] >= 2
    assert (await graph.index_provenance())["commit_sha"] == "e" * 40


@pytest.mark.asyncio
async def test_a_failed_refresh_does_not_fail_the_release():
    """A stale graph is a degraded answer next run. A release that shipped and
    then reported failure because re-indexing broke is a worse one."""
    from app.agents.nodes import build_nodes
    from app.core.audit import AuditLogger
    from app.core.gate_controller import GateController
    from tests.dispatch_doubles import InMemoryDispatchStore, StubWorkDispatch
    from tests.implementation_doubles import StubSourceControl, WritingLLMProvider
    from tests.test_graph_runtime import (
        InMemoryAuditSink,
        StubBuildDeploy,
        StubCodeDesignContext,
        StubRequirementsSource,
        StubTestManagement,
    )

    class _Exploding:
        async def index(self, repo, ref="main"):
            raise ValueError("archive unavailable")

    logger = AuditLogger(InMemoryAuditSink())
    nodes = build_nodes(
        requirements_source=StubRequirementsSource(),
        code_design_context=StubCodeDesignContext(),
        test_management=StubTestManagement(),
        build_deploy=StubBuildDeploy(),
        work_dispatch=StubWorkDispatch(),
        dispatch_store=InMemoryDispatchStore(),
        context_graph=InMemoryContextGraph(),
        llm_provider=WritingLLMProvider(),
        source_control=StubSourceControl(),
        code_intelligence=_Exploding(),
        audit_logger=logger,
        gate_controller=GateController(logger),
        target_repo="acme/thing",
        max_retries=1,
    )

    result = await nodes["release"]({"run_id": "run-2", "implementation": {"files": ["a.py"]}})

    assert result["status"] == "completed"
    assert "archive unavailable" in result["graph_update"]["failed"]
