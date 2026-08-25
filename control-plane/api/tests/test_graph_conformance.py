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
