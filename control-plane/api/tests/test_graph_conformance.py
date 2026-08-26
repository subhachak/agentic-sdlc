"""The production graph and its test double must present the same surface.

Every other graph test runs against InMemoryContextGraph. That is a deliberate
trade — a real database per test is slow — but it means the double is the only
thing under test, and a signature that drifts apart from SqlContextGraph is
invisible until someone clicks the button in the console.

That is not hypothetical. `phase_edges` gained a `project` parameter in the
protocol, in the double, and in its own *body*, but not in the production
signature; 392 tests stayed green and "Update from the repository" raised
TypeError on the first real call.

So this pins all three together. It compares signatures rather than behaviour,
which is cheap and catches the whole class rather than one instance.
"""

from __future__ import annotations

import inspect

import pytest

from app.core.context_graph import ContextGraphStore, SqlContextGraph
from tests.graph_doubles import InMemoryContextGraph

# Methods the protocol declares. Anything a caller can reach through the
# protocol has to exist on both implementations with a compatible signature.
PROTOCOL_METHODS = sorted(
    name
    for name, member in vars(ContextGraphStore).items()
    if not name.startswith("_") and inspect.isfunction(member)
)


def _params(fn) -> dict[str, inspect.Parameter]:
    return {
        name: p
        for name, p in inspect.signature(fn).parameters.items()
        if name != "self"
    }


def test_protocol_is_not_empty():
    # A typo in the introspection above would otherwise make every test below
    # vacuously pass.
    assert len(PROTOCOL_METHODS) > 10


@pytest.mark.parametrize("name", PROTOCOL_METHODS)
@pytest.mark.parametrize("impl", [SqlContextGraph, InMemoryContextGraph],
                         ids=["production", "double"])
def test_implements_protocol_method(impl, name):
    assert hasattr(impl, name), f"{impl.__name__} is missing {name}()"


@pytest.mark.parametrize("name", PROTOCOL_METHODS)
@pytest.mark.parametrize("impl", [SqlContextGraph, InMemoryContextGraph],
                         ids=["production", "double"])
def test_accepts_every_protocol_parameter(impl, name):
    """An implementation may accept more than the protocol promises, never less.

    A caller that reads the protocol and passes `project=` has to work against
    whichever implementation is wired in.
    """
    declared = _params(getattr(ContextGraphStore, name))
    actual = _params(getattr(impl, name))
    missing = sorted(set(declared) - set(actual))
    assert not missing, (
        f"{impl.__name__}.{name}() does not accept {missing}, "
        f"which the protocol declares"
    )


@pytest.mark.parametrize("name", PROTOCOL_METHODS)
def test_double_matches_production(name):
    """The double must not be more permissive than the thing it stands in for.

    A parameter the double accepts and production does not is a test that
    passes on a call the platform cannot serve.
    """
    prod = _params(getattr(SqlContextGraph, name))
    fake = _params(getattr(InMemoryContextGraph, name))
    extra = sorted(set(fake) - set(prod))
    assert not extra, (
        f"the double accepts {extra} on {name}() but production does not — "
        f"a test using it would pass on a call that fails at runtime"
    )


@pytest.mark.parametrize("name", PROTOCOL_METHODS)
def test_project_parameter_defaults_agree(name):
    """Where both take `project`, they must default the same way.

    Different defaults mean the double answers for one project and production
    for another, silently.
    """
    prod = _params(getattr(SqlContextGraph, name))
    fake = _params(getattr(InMemoryContextGraph, name))
    if "project" not in prod or "project" not in fake:
        return
    assert prod["project"].default == fake["project"].default, name


# ─── the production path itself ──────────────────────────────────────────────
# Signature conformance above would have caught the TypeError. This exercises
# the real class against a real database, because "the signature is right" and
# "the query runs" are different claims and only one of them is checkable by
# inspection.

@pytest.mark.asyncio
async def test_phase_edges_runs_against_a_real_database(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'graph.db'}")
    from app.core.config import get_settings
    from app.core.context_graph import Assertion, NodeSpec
    from app.core.db import get_engine, init_db
    from app.graph.projects import DEFAULT_PROJECT

    get_settings.cache_clear()
    get_engine.cache_clear()
    await init_db()

    from app.adapters.entity_resolver.local import LocalEntityResolver

    graph = SqlContextGraph(LocalEntityResolver())
    a = Assertion(
        edge="IMPORTS",
        src=NodeSpec(type="SOURCE_ARTIFACT", system="code", external_id="a.ts"),
        dst=NodeSpec(type="SOURCE_ARTIFACT", system="code", external_id="b.ts"),
    )
    await graph.ingest("run-1", "code-index", [a])

    # Positionally, as core.seeding.refresh calls it.
    edges = await graph.phase_edges("code-index", DEFAULT_PROJECT)
    assert ("IMPORTS", "a.ts", "b.ts") in edges

    # And by keyword, as the protocol invites.
    assert await graph.phase_edges("code-index", project=DEFAULT_PROJECT) == edges

    # A project that owns nothing sees nothing, rather than everything.
    assert await graph.phase_edges("code-index", "other-project") == set()

    get_settings.cache_clear()
    get_engine.cache_clear()


# ── shapes, not just signatures ───────────────────────────────────────────


def _returned_keys(path: str, class_name: str) -> dict[str, set[str]]:
    """Which string keys each method builds into a dict it returns.

    Static rather than executed: running both implementations needs a
    database and a populated graph, and the divergence being hunted is
    visible without either. Approximate on purpose — it over-collects keys
    from intermediate dicts — which is why the assertion below compares
    against a stated expectation rather than demanding equality.
    """
    import ast
    from pathlib import Path

    tree = ast.parse(Path(path).read_text())
    out: dict[str, set[str]] = {}
    for cls in [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == class_name]:
        for fn in cls.body:
            if not isinstance(fn, (ast.AsyncFunctionDef, ast.FunctionDef)):
                continue
            keys = {
                k.value
                for node in ast.walk(fn)
                if isinstance(node, ast.Dict)
                for k in node.keys
                if isinstance(k, ast.Constant) and isinstance(k.value, str)
            }
            if keys:
                out[fn.name] = keys
    return out


# What each method's items must contain, whoever implements the port.
#
# Written down here because the port cannot say it: these methods return
# `list[dict[str, Any]]`, so the shape lives in whatever the consumers
# happen to read. `modules()` diverged exactly this way — production
# returned `files` and the double returned `name`, so a consumer reading
# m["files"] worked against the database and raised KeyError against the
# double. The console's codebase view reads it three times.
REQUIRED_KEYS = {
    "modules": {"id", "files", "depends_on"},
    "module_catalogue": {"id", "files", "depends_on", "dependents", "paths", "hubs"},
    "criteria": {"id", "text"},
}


@pytest.mark.parametrize("method,required", sorted(REQUIRED_KEYS.items()))
@pytest.mark.parametrize(
    "source,cls",
    [
        ("app/core/context_graph.py", "SqlContextGraph"),
        ("tests/graph_doubles.py", "InMemoryContextGraph"),
    ],
    ids=["production", "double"],
)
def test_both_implementations_return_the_same_keys(source, cls, method, required):
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    produced = _returned_keys(str(root / source), cls)
    if method not in produced:
        pytest.skip(f"{cls} does not build {method}() inline")

    missing = sorted(required - produced[method])
    assert missing == [], (
        f"{cls}.{method}() does not produce {missing}. Consumers read these keys, "
        f"and the port's `list[dict[str, Any]]` cannot say so — which is why they "
        f"are listed here until the port carries models."
    )


# ── withdrawal is history, not deletion ───────────────────────────────────


@pytest.mark.asyncio
async def test_a_withdrawn_edge_is_kept_so_an_assessment_can_be_replayed(
    tmp_path, monkeypatch
):
    """superseded_at was on the model from the beginning and never assigned.

    Every query already filtered on it, so the append-only intent existed
    only as a column while retract and purge_phase deleted rows. That made an
    assessment unreproducible the moment the graph moved: "why did you select
    this test for that change" is unanswerable once the edges it reasoned
    over are gone.
    """
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'hist.db'}")
    from sqlalchemy import select

    from app.adapters.entity_resolver.local import LocalEntityResolver
    from app.core.config import get_settings
    from app.core.context_graph import Assertion, NodeSpec
    from app.core.db import get_engine, get_sessionmaker, init_db
    from app.models.graph import GraphEdge

    get_settings.cache_clear()
    get_engine.cache_clear()
    await init_db()

    graph = SqlContextGraph(LocalEntityResolver())
    edge = Assertion(
        edge="IMPORTS",
        src=NodeSpec(type="SOURCE_ARTIFACT", system="code", external_id="a.ts"),
        dst=NodeSpec(type="SOURCE_ARTIFACT", system="code", external_id="b.ts"),
    )
    await graph.ingest("run-1", "code-index", [edge])
    assert await graph.phase_edges("code-index") == {("IMPORTS", "a.ts", "b.ts")}

    await graph.retract("code-index", {("IMPORTS", "a.ts", "b.ts")})

    # Gone from the live view...
    assert await graph.phase_edges("code-index") == set()

    # ...and still on disk, stamped with when it was withdrawn.
    async with get_sessionmaker()() as session:
        rows = (await session.execute(select(GraphEdge))).scalars().all()
    assert len(rows) == 1
    assert rows[0].superseded_at is not None

    get_settings.cache_clear()
    get_engine.cache_clear()


def test_the_double_withdraws_rather_than_deleting_too():
    """It removed rows, so a test could not tell "withdrawn" from "never
    asserted" — the exact history that makes a replay possible."""
    import asyncio

    from app.core.context_graph import Assertion, NodeSpec

    graph = InMemoryContextGraph()
    asyncio.run(graph.ingest("run-1", "code-index", [
        Assertion(
            edge="IMPORTS",
            src=NodeSpec(type="SOURCE_ARTIFACT", system="code", external_id="a.ts"),
            dst=NodeSpec(type="SOURCE_ARTIFACT", system="code", external_id="b.ts"),
        )
    ]))
    asyncio.run(graph.retract("code-index", {("IMPORTS", "a.ts", "b.ts")}))

    assert graph.live == []
    assert len(graph.edges) == 1
    assert graph.edges[0]["superseded_at"] is not None
