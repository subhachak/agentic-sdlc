"""One button, and what it refuses to call success.

Setup was four buttons and three text boxes that had to agree with each
other. Everything they asked for is derivable: whether this is a first index
or a delta is a question about the graph, the ref is a property of the
repository, the scope is a property of the code just indexed.
"""

import pytest

from app.core import sync as sync_core
from app.ports.code_intelligence import (
    CodeFile,
    CodeIndex,
    CodeModule,
    IndexProvenance,
)
from tests.graph_doubles import InMemoryContextGraph


class FakeIndexer:
    def __init__(self, units, paths):
        self._units, self._paths = units, paths
        self.calls = 0

    async def index(self, repo: str, ref: str = "main") -> CodeIndex:
        self.calls += 1
        modules = sorted({p.rsplit("/", 1)[0] for p in self._paths})
        return CodeIndex(
            repo=repo,
            ref=ref,
            modules=[
                CodeModule(id=m, paths=[p for p in self._paths if p.startswith(m + "/")])
                for m in modules
            ],
            files=[
                CodeFile(path=p, module=p.rsplit("/", 1)[0], language="ts")
                for p in self._paths
            ],
            provenance=IndexProvenance(commit_sha="abc1234", units=self._units),
        )


class Retrieval:
    def __init__(self, chunks: int, problem: str | None = None):
        self._chunks, self._problem = chunks, problem

    async def rebuild(self):
        return {"chunks": self._chunks, "problem": self._problem}


def steps_by_name(result):
    return {s["step"]: s for s in result["steps"]}


@pytest.mark.asyncio
async def test_first_run_indexes_and_second_run_updates(tmp_path):
    graph = InMemoryContextGraph()
    indexer = FakeIndexer(["src"], ["src/a.ts", "src/b.ts"])
    out = tmp_path / "code-graph.json"

    first = await sync_core.sync(
        graph, indexer, Retrieval(12), repo="o/r", export_path=out
    )
    assert first["first_time"] is True
    assert steps_by_name(first)["index"]["mode"] == "full"

    second = await sync_core.sync(
        graph, indexer, Retrieval(12), repo="o/r", export_path=out
    )
    # Nobody told it which of these to do — it asked the graph.
    assert second["first_time"] is False
    assert steps_by_name(second)["index"]["mode"] == "delta"


@pytest.mark.asyncio
async def test_a_single_unit_repository_never_asks_about_scope(tmp_path):
    graph = InMemoryContextGraph()
    indexer = FakeIndexer(["src"], ["src/a.ts"])
    out = tmp_path / "code-graph.json"

    result = await sync_core.sync(graph, indexer, Retrieval(5), repo="o/r", export_path=out)
    assert result["ok"] is True
    assert steps_by_name(result)["export"]["status"] == "ok"
    assert out.exists()


@pytest.mark.asyncio
async def test_a_monorepo_asks_instead_of_exporting_the_wrong_thing(tmp_path):
    graph = InMemoryContextGraph()
    indexer = FakeIndexer(["apps/web", "apps/api"], ["apps/web/a.ts", "apps/api/b.ts"])
    out = tmp_path / "code-graph.json"

    result = await sync_core.sync(graph, indexer, Retrieval(5), repo="o/r", export_path=out)
    assert result["ok"] is False
    export = steps_by_name(result)["export"]
    assert export["status"] == "needs_choice"
    assert {c["path"] for c in export["candidates"]} == {"apps/web", "apps/api", ""}
    # Nothing was written, rather than something arbitrary.
    assert not out.exists()


@pytest.mark.asyncio
async def test_answering_the_question_completes_the_sync(tmp_path):
    graph = InMemoryContextGraph()
    indexer = FakeIndexer(["apps/web", "apps/api"], ["apps/web/a.ts", "apps/api/b.ts"])
    out = tmp_path / "code-graph.json"

    result = await sync_core.sync(
        graph, indexer, Retrieval(5), repo="o/r", scope="apps/web", export_path=out
    )
    assert result["ok"] is True
    assert steps_by_name(result)["export"]["scope"] == "apps/web"
    assert out.exists()


@pytest.mark.asyncio
async def test_an_empty_retrieval_index_is_a_failure_not_a_tick(tmp_path):
    """The defect this guards: grounding read zero files because it was
    pointed at a different repository from the one indexed, and the console
    reported the step as done, in green."""
    graph = InMemoryContextGraph()
    indexer = FakeIndexer(["src"], ["src/a.ts"])

    result = await sync_core.sync(
        graph,
        indexer,
        Retrieval(0, problem="read 0 of 343 files"),
        repo="o/r",
        export_path=tmp_path / "g.json",
    )
    retrieval = steps_by_name(result)["retrieval"]
    assert retrieval["status"] == "failed"
    assert "read 0 of 343 files" in retrieval["summary"]
    assert result["ok"] is False


@pytest.mark.asyncio
async def test_an_adapter_with_no_index_to_build_is_skipped_not_failed(tmp_path):
    class NoRebuild:
        pass

    graph = InMemoryContextGraph()
    indexer = FakeIndexer(["src"], ["src/a.ts"])
    result = await sync_core.sync(
        graph, indexer, NoRebuild(), repo="o/r", export_path=tmp_path / "g.json"
    )
    assert steps_by_name(result)["retrieval"]["status"] == "skipped"
    assert result["ok"] is True


@pytest.mark.asyncio
async def test_changing_repository_reindexes_rather_than_diffing(tmp_path):
    """A delta against a different repository would retract every edge the
    old one asserted and call it a change."""
    graph = InMemoryContextGraph()
    out = tmp_path / "g.json"
    await sync_core.sync(
        graph, FakeIndexer(["src"], ["src/a.ts"]), Retrieval(3), repo="o/first", export_path=out
    )
    second = await sync_core.sync(
        graph, FakeIndexer(["src"], ["src/a.ts"]), Retrieval(3), repo="o/second", export_path=out
    )
    assert second["first_time"] is True
    assert steps_by_name(second)["index"]["mode"] == "full"
