"""The design phase decides what the implementation phase may touch.

It used to pick components by word overlap between the requirement text and
directory names, then hand the implementation agent the first twelve files it
found. Containment was enforced against that — which meant it constrained
nothing, and a human at gate 2 was approving a fixed string.

These tests are about what the phase now refuses.
"""

from __future__ import annotations

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from app.agents.graph import build_graph
from app.agents.nodes import build_nodes
from app.agents.state import PipelineConfig
from app.core.audit import AuditLogger
from app.core.design_review import MAX_COMPONENTS, MAX_FILES, impact_set, review
from app.core.gate_controller import GateController
from tests.dispatch_doubles import SUCCESS, InMemoryDispatchStore, StubWorkDispatch
from tests.graph_doubles import InMemoryContextGraph
from tests.implementation_doubles import StubSourceControl, WritingLLMProvider
from tests.test_graph_runtime import (
    InMemoryAuditSink,
    StubBuildDeploy,
    StubCodeDesignContext,
    StubRequirementsSource,
    StubTestManagement,
)

KNOWN = {
    "demo-app/app/claims": {"demo-app/app/claims/page.tsx"},
    "demo-app/app/api": {"demo-app/app/api/claims/route.ts"},
    "demo-app/lib": {"demo-app/lib/data-store.json"},
}
DEPENDENTS = {"demo-app/app/api": {"demo-app/app/claims"}}


def _design(**overrides):
    base = {
        "summary": "render the table only when there are rows",
        "rationale": "the criterion concerns the claims list, which this component owns",
        "components": ["demo-app/app/claims"],
        "files": ["demo-app/app/claims/page.tsx"],
        "criteria_addressed": ["ac-1"],
        "out_of_scope": [],
    }
    return {**base, **overrides}


def _review(proposal, criteria={"ac-1"}):
    return review(proposal, known_components=KNOWN, dependents=DEPENDENTS, known_criteria=criteria)


# --- what it accepts -------------------------------------------------------


def test_a_design_naming_real_components_and_files_is_accepted():
    verdict = _review(_design())
    assert verdict.allowed is True
    assert verdict.reasons == []


def test_impact_is_derived_from_dependency_edges_not_proposed():
    """An architect can be wrong about consequences. The edges cannot."""
    verdict = _review(_design(components=["demo-app/app/api"],
                              files=["demo-app/app/api/claims/route.ts"]))
    assert verdict.impact == ["demo-app/app/api", "demo-app/app/claims"]


def test_impact_of_a_leaf_component_is_itself():
    assert impact_set(["demo-app/lib"], DEPENDENTS) == ["demo-app/lib"]


# --- what it refuses -------------------------------------------------------


def test_a_component_that_does_not_exist_is_refused():
    """The failure the whole containment claim rested on: a design naming
    something nobody has heard of, approved by a human, then used to constrain
    the implementation agent."""
    verdict = _review(_design(components=["demo-app/app/invented"]))
    assert verdict.allowed is False
    assert "unknown component 'demo-app/app/invented'" in verdict.reasons


def test_a_file_that_does_not_exist_is_refused():
    verdict = _review(_design(files=["demo-app/app/claims/nope.tsx"]))
    assert any("unknown file" in r for r in verdict.reasons)


def test_a_file_outside_the_named_components_is_refused():
    """Otherwise the implementation agent is handed a file it is then forbidden
    to edit, and the run dies one phase later for no visible reason."""
    verdict = _review(_design(files=["demo-app/app/api/claims/route.ts"]))
    assert any("not in any component the design named" in r for r in verdict.reasons)


def test_a_design_naming_no_files_is_refused():
    verdict = _review(_design(files=[]))
    assert any("would see nothing" in r for r in verdict.reasons)


def test_a_criterion_neither_addressed_nor_excused_is_refused():
    verdict = _review(_design(), criteria={"ac-1", "ac-2"})
    assert any("neither addressed nor declared out of scope" in r for r in verdict.reasons)


def test_a_criterion_may_be_declared_out_of_scope_with_the_others_addressed():
    verdict = _review(_design(out_of_scope=["ac-2"]), criteria={"ac-1", "ac-2"})
    assert verdict.allowed is True


def test_a_design_without_a_rationale_is_refused():
    """A human approving at gate 2 needs something to approve."""
    verdict = _review(_design(rationale="  "))
    assert any("no rationale" in r for r in verdict.reasons)


def test_a_sprawling_design_is_refused():
    verdict = _review(_design(components=[f"c{i}" for i in range(MAX_COMPONENTS + 1)]))
    assert any("more than the" in r for r in verdict.reasons)


def test_too_many_files_is_refused():
    verdict = _review(_design(files=[f"f{i}.ts" for i in range(MAX_FILES + 1)]))
    assert any(f"more than the {MAX_FILES}" in r for r in verdict.reasons)


def test_an_empty_graph_is_reported_not_silently_passed():
    """A design validated against nothing has not been validated, and the run
    should say so rather than imply a check happened."""
    verdict = review(_design(), known_components={}, dependents={}, known_criteria=set())
    assert verdict.allowed is True
    assert "not validated" in verdict.reasons[0]


# --- in the graph ----------------------------------------------------------


async def _drive_to_gate_2(graph, run_id):
    thread = {"configurable": {"thread_id": run_id}}
    await graph.ainvoke(
        {"run_id": run_id,
         "config": PipelineConfig(auto_approve_gates=False, max_node_retries=1),
         "raw_input": {"text": "show only the empty state", "file_bytes": None, "filename": None}},
        config=thread,
    )
    return await graph.ainvoke(Command(resume={"approved": True}), config=thread)


def _graph(llm, store):
    logger = AuditLogger(InMemoryAuditSink())
    nodes = build_nodes(
        requirements_source=StubRequirementsSource(),
        code_design_context=StubCodeDesignContext(),
        test_management=StubTestManagement(),
        build_deploy=StubBuildDeploy(),
        work_dispatch=StubWorkDispatch(SUCCESS),
        source_control=StubSourceControl(),
        dispatch_store=InMemoryDispatchStore(),
        context_graph=store,
        llm_provider=llm,
        audit_logger=logger,
        gate_controller=GateController(logger),
        max_retries=1,
    )
    return build_graph(nodes, checkpointer=MemorySaver())


async def _seeded_store():
    from app.core.context_graph import Assertion, NodeSpec

    store = InMemoryContextGraph()
    await store.ingest("seed", "code-index", [
        Assertion("BELONGS_TO",
                  NodeSpec("SOURCE_ARTIFACT", "code", "demo-app/app/claims/page.tsx", {}),
                  NodeSpec("COMPONENT", "code", "demo-app/app/claims", {"file_count": 1})),
    ])
    return store


@pytest.mark.asyncio
async def test_gate_2_now_pauses_in_front_of_a_real_design():
    """Previously the payload was a fixed string and the audit trail recorded
    an approval made on no information."""
    store = await _seeded_store()
    result = await _drive_to_gate_2(
        _graph(WritingLLMProvider(components=["demo-app/app/claims"]), store), "d-1"
    )

    payload = result["__interrupt__"][0].value
    assert payload["type"] == "design_approval"
    assert payload["components"] == ["demo-app/app/claims"]
    assert payload["files"] == ["demo-app/app/claims/page.tsx"]
    assert payload["rationale"]


@pytest.mark.asyncio
async def test_a_design_naming_an_unknown_component_never_reaches_a_human():
    store = await _seeded_store()
    result = await _drive_to_gate_2(
        _graph(WritingLLMProvider(components=["not/a/component"]), store), "d-2"
    )

    assert result["status"] == "design_rejected"
    assert "__interrupt__" not in result
    assert any("unknown component" in r for r in result["design_proposal"]["rejected"])


@pytest.mark.asyncio
async def test_a_rejected_design_never_reaches_implementation():
    store = await _seeded_store()
    result = await _drive_to_gate_2(
        _graph(WritingLLMProvider(components=["not/a/component"]), store), "d-3"
    )
    assert result.get("implementation") is None
