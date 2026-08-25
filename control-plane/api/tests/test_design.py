"""The design phase decides what the implementation phase may touch.

It used to pick modules by word overlap between the requirement text and
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
from app.core.design_review import MAX_MODULES, MAX_FILES, impact_set, review
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
# file -> the files that import it
FILE_DEPENDENTS = {
    "demo-app/app/api/claims/route.ts": {"demo-app/app/claims/page.tsx"},
}


def _design(**overrides):
    base = {
        "summary": "render the table only when there are rows",
        "rationale": "the criterion concerns the claims list, which this module owns",
        "modules": ["demo-app/app/claims"],
        "files": ["demo-app/app/claims/page.tsx"],
        "criteria_addressed": ["ac-1"],
        "out_of_scope": [],
    }
    return {**base, **overrides}


def _review(proposal, criteria={"ac-1"}):
    return review(proposal, known_modules=KNOWN, file_dependents=FILE_DEPENDENTS,
                  known_criteria=criteria)


# --- what it accepts -------------------------------------------------------


def test_a_design_naming_real_modules_and_files_is_accepted():
    verdict = _review(_design())
    assert verdict.allowed is True
    assert verdict.reasons == []


def test_impact_is_derived_from_import_edges_not_proposed():
    """An architect can be wrong about consequences. The edges cannot."""
    verdict = _review(_design(modules=["demo-app/app/api"],
                              files=["demo-app/app/api/claims/route.ts"]))

    assert verdict.impact["files"] == ["demo-app/app/claims/page.tsx"]
    assert "demo-app/app/claims" in verdict.impact["modules"]


def test_impact_distinguishes_a_hub_from_a_leaf():
    """The failure module-level impact could not express: every file in a
    directory scored identically, so a leaf and the models file forty things
    import looked the same."""
    path_to_module = {p: m for m, ps in KNOWN.items() for p in ps}

    hub = impact_set(["demo-app/app/api/claims/route.ts"], FILE_DEPENDENTS, path_to_module)
    leaf = impact_set(["demo-app/app/claims/page.tsx"], FILE_DEPENDENTS, path_to_module)

    assert hub["files"] == ["demo-app/app/claims/page.tsx"]
    assert leaf["files"] == []


def test_a_deeper_traversal_reaches_further():
    fd = {"a.py": {"b.py"}, "b.py": {"c.py"}}
    assert impact_set(["a.py"], fd, depth=1)["files"] == ["b.py"]
    assert impact_set(["a.py"], fd, depth=2)["files"] == ["b.py", "c.py"]


# --- what it refuses -------------------------------------------------------


def test_a_module_that_does_not_exist_is_refused():
    """The failure the whole containment claim rested on: a design naming
    something nobody has heard of, approved by a human, then used to constrain
    the implementation agent."""
    verdict = _review(_design(modules=["demo-app/app/invented"]))
    assert verdict.allowed is False
    assert "unknown module 'demo-app/app/invented'" in verdict.reasons


def test_a_file_that_does_not_exist_is_refused():
    verdict = _review(_design(files=["demo-app/app/claims/nope.tsx"]))
    assert any("unknown file" in r for r in verdict.reasons)


def test_a_file_outside_the_named_modules_is_refused():
    """Otherwise the implementation agent is handed a file it is then forbidden
    to edit, and the run dies one phase later for no visible reason."""
    verdict = _review(_design(files=["demo-app/app/api/claims/route.ts"]))
    assert any("not in any module the design named" in r for r in verdict.reasons)


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
    verdict = _review(_design(modules=[f"c{i}" for i in range(MAX_MODULES + 1)]))
    assert any("more than the" in r for r in verdict.reasons)


def test_too_many_files_is_refused():
    verdict = _review(_design(files=[f"f{i}.ts" for i in range(MAX_FILES + 1)]))
    assert any(f"more than the {MAX_FILES}" in r for r in verdict.reasons)


def test_an_empty_graph_refuses_rather_than_passing():
    """A design validated against nothing has not been validated. This used to
    return allowed=True with a note attached, which meant the one condition
    guaranteeing containment could not work was also the one condition under
    which every design was admitted."""
    verdict = review(_design(), known_modules={}, file_dependents={}, known_criteria=set())

    assert verdict.allowed is False
    assert "holds no modules" in verdict.reasons[0]
    assert verdict.impact == {"files": [], "modules": []}


def test_a_graph_that_resolved_too_little_refuses_and_says_what_it_missed():
    """Containment is only as good as the edges behind it. A graph that
    dropped a fifth of its internal imports can approve a design whose real
    impact set is unknowable, so it declines and names the specifiers it could
    not resolve."""
    verdict = review(
        _design(),
        known_modules={"demo-app/app/claims": {"demo-app/app/claims/page.tsx"}},
        file_dependents={},
        graph_quality={
            "internal_capture_rate": 0.62,
            "most_missed": [("@/lib/api", 6), ("@/lib/types", 6)],
        },
    )

    assert verdict.allowed is False
    assert "62.0%" in verdict.reasons[0]
    assert "@/lib/api" in verdict.reasons[0]


def test_a_healthy_graph_is_reviewed_normally():
    verdict = review(
        _design(),
        known_modules={"demo-app/app/claims": {"demo-app/app/claims/page.tsx"}},
        file_dependents={},
        graph_quality={"internal_capture_rate": 0.93, "most_missed": []},
    )
    assert verdict.allowed is True


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
                  NodeSpec("MODULE", "code", "demo-app/app/claims", {"file_count": 1})),
    ])
    return store


@pytest.mark.asyncio
async def test_gate_2_now_pauses_in_front_of_a_real_design():
    """Previously the payload was a fixed string and the audit trail recorded
    an approval made on no information."""
    store = await _seeded_store()
    result = await _drive_to_gate_2(
        _graph(WritingLLMProvider(modules=["demo-app/app/claims"]), store), "d-1"
    )

    payload = result["__interrupt__"][0].value
    assert payload["type"] == "design_approval"
    assert payload["modules"] == ["demo-app/app/claims"]
    assert payload["files"] == ["demo-app/app/claims/page.tsx"]
    assert payload["rationale"]


@pytest.mark.asyncio
async def test_a_design_naming_an_unknown_module_never_reaches_a_human():
    store = await _seeded_store()
    result = await _drive_to_gate_2(
        _graph(WritingLLMProvider(modules=["not/a/module"]), store), "d-2"
    )

    assert result["status"] == "design_rejected"
    assert "__interrupt__" not in result
    assert any("unknown module" in r for r in result["design_proposal"]["rejected"])


@pytest.mark.asyncio
async def test_a_rejected_design_never_reaches_implementation():
    store = await _seeded_store()
    result = await _drive_to_gate_2(
        _graph(WritingLLMProvider(modules=["not/a/module"]), store), "d-3"
    )
    assert result.get("implementation") is None
