"""Keeping one project's graph out of another's.

The graph was single-project by construction and silently so. `purge_phase`
removed every edge its phase had ever written, regardless of repository — so
indexing a second repository deleted the first, with no error and no warning.
The first team's next design phase simply refused against an empty graph,
which is indistinguishable from never having seeded one.
"""

from __future__ import annotations

import pytest

from app.core.seeding import seed
from app.graph.identity import node_id
from app.graph.projects import DEFAULT_PROJECT, ProjectError, project_of, scoped, validate
from app.ports.code_intelligence import (
    CodeFile,
    CodeIndex,
    CodeModule,
    FileImport,
    IndexProvenance,
)
from tests.graph_doubles import InMemoryContextGraph


def _index(repo: str, files: list[str], commit: str = "a" * 40) -> CodeIndex:
    return CodeIndex(
        repo=repo,
        ref="main",
        modules=[CodeModule(id=f"{repo}/app", paths=sorted(files))],
        files=[CodeFile(path=p, module=f"{repo}/app") for p in sorted(files)],
        imports=[FileImport(source=files[0], target=files[-1])] if len(files) > 1 else [],
        provenance=IndexProvenance(commit_sha=commit, indexer_version="test"),
    )


class _Indexer:
    def __init__(self, index: CodeIndex) -> None:
        self._index = index

    async def index(self, repo: str, ref: str = "main") -> CodeIndex:
        return self._index


# --- the naming rule -------------------------------------------------------


def test_the_default_project_is_unqualified():
    """So a single-project deployment needs no re-index, and a graph written
    before projects existed is still readable rather than stranded in a
    namespace nobody queries."""
    assert scoped("code") == "code"
    assert scoped("code", DEFAULT_PROJECT) == "code"
    assert project_of("code") == DEFAULT_PROJECT


def test_a_project_qualifies_the_system():
    assert scoped("code", "team-a") == "code@team-a"
    assert project_of("code@team-a") == "team-a"


def test_two_projects_give_the_same_path_different_identities():
    """Without this they collide, and each index overwrites the other's
    projections rather than sitting beside them."""
    a = node_id("SOURCE_ARTIFACT", scoped("code", "team-a"), "app/page.tsx")
    b = node_id("SOURCE_ARTIFACT", scoped("code", "team-b"), "app/page.tsx")

    assert a != b


def test_an_ambiguous_project_id_is_refused():
    """Project ids end up inside node identity, so `a@b` would make
    `code@a@b` unparseable."""
    for bad in ("Team A", "a@b", "", "x" * 64, "-leading"):
        with pytest.raises(ProjectError):
            validate(bad)


# --- isolation -------------------------------------------------------------


@pytest.mark.asyncio
async def test_indexing_a_second_project_does_not_delete_the_first():
    """The bug, exactly as it was: seeding team-b wiped team-a's graph."""
    graph = InMemoryContextGraph()

    await seed(graph, _Indexer(_index("team-a", ["team-a/app/x.py"])),
               repo="team-a", project="team-a")
    await seed(graph, _Indexer(_index("team-b", ["team-b/app/y.py"])),
               repo="team-b", project="team-b")

    assert await graph.module_paths("team-a") == {"team-a/app": {"team-a/app/x.py"}}
    assert await graph.module_paths("team-b") == {"team-b/app": {"team-b/app/y.py"}}


@pytest.mark.asyncio
async def test_re_indexing_one_project_leaves_the_others_alone():
    graph = InMemoryContextGraph()
    await seed(graph, _Indexer(_index("team-a", ["team-a/app/x.py"])),
               repo="team-a", project="team-a")
    await seed(graph, _Indexer(_index("team-b", ["team-b/app/y.py"])),
               repo="team-b", project="team-b")

    await seed(graph, _Indexer(_index("team-a", ["team-a/app/z.py"])),
               repo="team-a", project="team-a")

    assert await graph.module_paths("team-a") == {"team-a/app": {"team-a/app/z.py"}}
    assert await graph.module_paths("team-b") == {"team-b/app": {"team-b/app/y.py"}}


@pytest.mark.asyncio
async def test_a_project_reads_only_its_own_counts_and_provenance():
    graph = InMemoryContextGraph()
    await seed(graph, _Indexer(_index("team-a", ["team-a/app/x.py", "team-a/app/w.py"],
                                      commit="a" * 40)),
               repo="team-a", project="team-a")
    await seed(graph, _Indexer(_index("team-b", ["team-b/app/y.py"], commit="b" * 40)),
               repo="team-b", project="team-b")

    assert (await graph.index_provenance("team-a"))["commit_sha"] == "a" * 40
    assert (await graph.index_provenance("team-b"))["commit_sha"] == "b" * 40
    assert (await graph.counts("team-a"))["nodes"]["SOURCE_ARTIFACT"] == 2
    assert (await graph.counts("team-b"))["nodes"]["SOURCE_ARTIFACT"] == 1


@pytest.mark.asyncio
async def test_impact_does_not_cross_a_project_boundary():
    """The consequence that would matter most: a design in one project being
    told it reaches files in another client's codebase."""
    graph = InMemoryContextGraph()
    await seed(graph, _Indexer(_index("team-a", ["team-a/app/a.py", "team-a/app/b.py"])),
               repo="team-a", project="team-a")
    await seed(graph, _Indexer(_index("team-b", ["team-b/app/c.py", "team-b/app/d.py"])),
               repo="team-b", project="team-b")

    reachable = await graph.file_dependents("team-a")

    assert all(
        path.startswith("team-a/") and all(s.startswith("team-a/") for s in sources)
        for path, sources in reachable.items()
    )


@pytest.mark.asyncio
async def test_the_default_project_sees_neither():
    """Unqualified reads must not quietly aggregate every client's code."""
    graph = InMemoryContextGraph()
    await seed(graph, _Indexer(_index("team-a", ["team-a/app/x.py"])),
               repo="team-a", project="team-a")

    assert await graph.module_paths() == {}
    assert (await graph.counts())["nodes"] == {}


@pytest.mark.asyncio
async def test_an_existing_unscoped_graph_is_readable_as_the_default_project():
    """A graph written before projects existed stays queryable rather than
    needing a re-index nobody was told to run."""
    graph = InMemoryContextGraph()
    await seed(graph, _Indexer(_index("legacy", ["legacy/app/x.py"])), repo="legacy")

    assert await graph.module_paths() == {"legacy/app": {"legacy/app/x.py"}}
    assert await graph.module_paths("team-a") == {}


@pytest.mark.asyncio
async def test_the_seed_result_names_the_project_it_wrote():
    graph = InMemoryContextGraph()
    summary = await seed(graph, _Indexer(_index("team-a", ["team-a/app/x.py"])),
                         repo="team-a", project="team-a")

    assert summary["project"] == "team-a"
