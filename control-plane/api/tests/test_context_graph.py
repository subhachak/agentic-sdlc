"""The context graph: the ontology it enforces, the identity it derives, and
the queries that justify its existence.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from app.core.context_graph import Assertion, NodeSpec
from app.graph.identity import node_id
from app.graph.ontology import EdgeType, NodeType, OntologyError, validate_edge, validate_node_type
from tests.graph_doubles import InMemoryContextGraph


# --- the identity layer both planes depend on ------------------------------


def _execution_plane_identity():
    """Import the execution plane's copy directly. It is stdlib-only, so this
    works across the two dependency sets."""
    path = (
        Path(__file__).resolve().parents[3]
        / "execution-plane" / "qa" / "orchestrator" / "identity.py"
    )
    spec = importlib.util.spec_from_file_location("qa_identity", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_both_planes_derive_the_same_node_id():
    """The identity function is duplicated across two packages that cannot
    import each other. If the copies drift, every edge the QA pipeline emits
    points at a node the control plane has never heard of — silently."""
    other = _execution_plane_identity()

    assert other.NAMESPACE == __import__("app.graph.identity", fromlist=["NAMESPACE"]).NAMESPACE
    for args in [
        ("ACCEPTANCE_CRITERION", "features", "claims-status-filter/ac-2"),
        ("TEST_SCENARIO", "qa", "filter-denied"),
        ("COMPONENT", "code", "claims-api"),
    ]:
        assert node_id(*args) == other.node_id(*args), args


def test_identity_is_stable_and_type_sensitive():
    a = node_id("COMPONENT", "code", "claims-api")
    assert a == node_id("COMPONENT", "code", "claims-api")
    assert a != node_id("TEST_SCENARIO", "code", "claims-api")


# --- the ontology is fixed -------------------------------------------------


def test_a_legal_edge_is_accepted():
    validate_edge(EdgeType.VERIFIED_BY, NodeType.ACCEPTANCE_CRITERION, NodeType.TEST_SCENARIO)


def test_a_reversed_edge_is_rejected():
    with pytest.raises(OntologyError, match="goes"):
        validate_edge(EdgeType.VERIFIED_BY, NodeType.TEST_SCENARIO, NodeType.ACCEPTANCE_CRITERION)


def test_an_invented_edge_type_is_rejected():
    with pytest.raises(OntologyError, match="unknown edge type"):
        validate_edge("SORT_OF_RELATES_TO", NodeType.COMPONENT, NodeType.COMPONENT)


def test_an_invented_node_type_is_rejected():
    with pytest.raises(OntologyError, match="unknown node type"):
        validate_node_type("Widget")


def test_clients_extend_through_namespaced_types():
    """Room for a client's own taxonomy without forking the semantics: stored
    and displayed, never gated on."""
    validate_edge("x_acme:BOOKED_TO", "x_acme:CostCentre", NodeType.COMPONENT)
    validate_node_type("x_acme:RiskTier")


# --- population and queries ------------------------------------------------


def _ac(cid):
    return NodeSpec("ACCEPTANCE_CRITERION", "features", cid, {"text": cid})


def _scenario(sid):
    return NodeSpec("TEST_SCENARIO", "qa", sid, {"title": sid})


def _script(name):
    return NodeSpec("TEST_SCRIPT", "qa", name, {})


def _run(status):
    return NodeSpec("TEST_RUN", "qa", "acme/demo#7", {"status": status})


def _chain(cid, sid, status="passed"):
    return [
        Assertion("VERIFIED_BY", _ac(cid), _scenario(sid)),
        Assertion("IMPLEMENTED_BY", _scenario(sid), _script(f"{sid}.spec.ts")),
        Assertion("EXERCISED_IN", _script(f"{sid}.spec.ts"), _run(status)),
    ]


@pytest.mark.asyncio
async def test_ingest_writes_nodes_and_edges():
    graph = InMemoryContextGraph()
    written = await graph.ingest("run-1", "qa", _chain("ac-1", "filter-denied"))

    assert written == 3
    assert len(graph.nodes) == 4


@pytest.mark.asyncio
async def test_ingesting_the_same_result_twice_changes_nothing():
    """The reconciler can retry a resume, so the same assertions can arrive
    more than once. Derived ids and a unique edge key make that harmless."""
    graph = InMemoryContextGraph()
    first = await graph.ingest("run-1", "qa", _chain("ac-1", "filter-denied"))
    second = await graph.ingest("run-1", "qa", _chain("ac-1", "filter-denied"))

    assert (first, second) == (3, 0)
    assert len(graph.edges) == 3


@pytest.mark.asyncio
async def test_every_edge_records_the_run_that_asserted_it():
    graph = InMemoryContextGraph()
    await graph.ingest("run-42", "qa", _chain("ac-1", "s1"))

    assert {e["run_id"] for e in graph.edges} == {"run-42"}
    assert {e["phase"] for e in graph.edges} == {"qa"}


@pytest.mark.asyncio
async def test_an_illegal_edge_is_refused_at_ingest():
    graph = InMemoryContextGraph()
    with pytest.raises(OntologyError):
        await graph.ingest("run-1", "qa", [Assertion("VERIFIED_BY", _scenario("s"), _ac("a"))])


@pytest.mark.asyncio
async def test_untested_criteria_is_the_release_readiness_query():
    """A criterion whose chain never reaches a passing run is untested — the
    question a regulated client asks, and one no run log can answer."""
    graph = InMemoryContextGraph()
    await graph.ingest("run-1", "qa", _chain("covered/ac-1", "s-pass", status="passed"))
    await graph.ingest("run-1", "qa", [Assertion("VERIFIED_BY", _ac("planned/ac-2"), _scenario("s-none"))])

    untested = {c["external_id"] for c in await graph.untested_criteria()}

    assert untested == {"planned/ac-2"}


@pytest.mark.asyncio
async def test_a_failing_run_leaves_its_criterion_untested():
    graph = InMemoryContextGraph()
    await graph.ingest("run-1", "qa", _chain("ac-1", "s1", status="failed"))

    assert {c["external_id"] for c in await graph.untested_criteria()} == {"ac-1"}


@pytest.mark.asyncio
async def test_trace_walks_criterion_to_defect():
    graph = InMemoryContextGraph()
    await graph.ingest("run-1", "qa", _chain("ac-1", "s1", status="failed"))
    await graph.ingest("run-1", "qa", [
        Assertion("RAISED", _run("failed"), NodeSpec("DEFECT", "qa", "s1 failed", {}))
    ])

    trace = await graph.trace(node_id("ACCEPTANCE_CRITERION", "features", "ac-1"))

    assert [n["external_id"] for n in trace["scenarios"]] == ["s1"]
    assert [n["external_id"] for n in trace["defects"]] == ["s1 failed"]


@pytest.mark.asyncio
async def test_blast_radius_reaches_scenarios_through_a_dependency():
    graph = InMemoryContextGraph()
    api = NodeSpec("COMPONENT", "code", "claims-api", {})
    filt = NodeSpec("COMPONENT", "code", "claims-filter", {})
    await graph.ingest("run-1", "qa", [
        Assertion("DEPENDS_ON", filt, api),
        Assertion("COVERS", _scenario("filter-denied"), filt),
    ])

    reached = {s["external_id"] for s in await graph.blast_radius(
        node_id("COMPONENT", "code", "claims-api")
    )}

    assert reached == {"filter-denied"}
