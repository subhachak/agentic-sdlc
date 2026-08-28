"""Undoing a release.

Two layers that restore different things: the revert restores the repository
and, through the client's own automation, the running hosts; the retraction
restores the graph. They fail independently, which is why the endpoint runs
the revert first — a graph that no longer claims a release, over a repository
that still has it, is worse than either failure alone and reads as success.
"""

from __future__ import annotations

import pytest

from app.core.context_graph import Assertion, NodeSpec, SqlContextGraph


async def _graph(tmp_path, monkeypatch) -> SqlContextGraph:
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'rollback.db'}")
    from app.core.config import get_settings
    from app.core.db import get_engine, init_db

    get_settings.cache_clear()
    get_engine.cache_clear()
    await init_db()

    from app.adapters.entity_resolver.local import LocalEntityResolver

    return SqlContextGraph(LocalEntityResolver())


def _release(run_id: str, path: str) -> Assertion:
    return Assertion(
        "CONTAINS",
        NodeSpec("RELEASE", "pipeline", run_id[:8], {}),
        NodeSpec("SOURCE_ARTIFACT", "code", path, {}),
    )


@pytest.mark.asyncio
async def test_rolling_back_one_run_leaves_another_runs_release_alone(tmp_path, monkeypatch):
    """Edges are unique per run, so two releases containing the same file are
    two assertions that look identical. Retracting by tuple takes both, which
    is why this is scoped by run."""
    graph = await _graph(tmp_path, monkeypatch)
    await graph.ingest("run-a", "release", [_release("run-a", "app/lib/format.ts")])
    await graph.ingest("run-b", "release", [_release("run-b", "app/lib/format.ts")])

    withdrawn = await graph.retract_run("run-a", "release")

    assert withdrawn["edges"] == 1
    assert await graph.phase_edges("release"), "run-b's release must survive"


@pytest.mark.asyncio
async def test_a_withdrawn_release_is_superseded_not_deleted(tmp_path, monkeypatch):
    """"What did this run ship, and when was it withdrawn" is the question
    that follows an incident. Deleting makes it unanswerable."""
    graph = await _graph(tmp_path, monkeypatch)
    await graph.ingest("run-a", "release", [_release("run-a", "app/lib/format.ts")])

    await graph.retract_run("run-a", "release")

    assert await graph.phase_edges("release") == set()

    from sqlalchemy import select

    from app.core.db import get_sessionmaker
    from app.models.graph import GraphEdge

    async with get_sessionmaker()() as session:
        rows = (await session.execute(select(GraphEdge))).scalars().all()
    assert len(rows) == 1, "the edge is history, not garbage"
    assert rows[0].superseded_at is not None


@pytest.mark.asyncio
async def test_rolling_back_twice_does_not_move_the_withdrawal(tmp_path, monkeypatch):
    """A second rollback must not restamp the first — that would date the
    withdrawal to whenever somebody last ran the command."""
    graph = await _graph(tmp_path, monkeypatch)
    await graph.ingest("run-a", "release", [_release("run-a", "app/lib/format.ts")])

    first = await graph.retract_run("run-a", "release")
    second = await graph.retract_run("run-a", "release")

    assert (first["edges"], second["edges"]) == (1, 0)


@pytest.mark.asyncio
async def test_only_the_named_phase_is_withdrawn(tmp_path, monkeypatch):
    """A rollback undoes the release, not the run. What QA proved about the
    change stays true — the change still happened."""
    graph = await _graph(tmp_path, monkeypatch)
    await graph.ingest("run-a", "release", [_release("run-a", "app/lib/format.ts")])
    await graph.ingest("run-a", "qa", [_release("run-a", "app/lib/other.ts")])

    await graph.retract_run("run-a", "release")

    assert await graph.phase_edges("qa"), "the QA evidence is not undone by a rollback"


@pytest.mark.asyncio
async def test_a_run_that_never_released_retracts_nothing(tmp_path, monkeypatch):
    graph = await _graph(tmp_path, monkeypatch)
    assert await graph.retract_run("never-ran", "release") == {"edges": 0, "nodes": 0}
