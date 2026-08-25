"""The implementation phase: an agent writes the change, code decides whether
it may be proposed.

The tests that matter are the refusals. A phase that writes code is the one
place where an agent's output becomes a lasting artifact, so what it is not
allowed to do is more important than what it is.
"""

from __future__ import annotations

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from app.agents.graph import build_graph
from app.agents.nodes import build_nodes
from app.agents.state import PipelineConfig
from app.core.audit import AuditLogger
from app.core.change_review import MAX_FILES, review
from app.core.gate_controller import GateController
from tests.dispatch_doubles import SUCCESS, InMemoryDispatchStore, StubWorkDispatch
from tests.graph_doubles import InMemoryContextGraph, seeded_graph
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
}


# --- the deterministic review ----------------------------------------------


def test_a_change_inside_the_named_components_is_allowed():
    verdict = review(
        [{"path": "demo-app/app/claims/page.tsx", "content": "x"}],
        allowed_modules=["demo-app/app/claims"],
        known_modules=KNOWN,
    )
    assert verdict.allowed is True
    assert verdict.modules == ["demo-app/app/claims"]


def test_a_change_outside_them_is_refused():
    """The payoff of the context graph: what the design named is checkable,
    so an agent editing something nobody agreed to is caught before it runs."""
    verdict = review(
        [{"path": "demo-app/app/api/claims/route.ts", "content": "x"}],
        allowed_modules=["demo-app/app/claims"],
        known_modules=KNOWN,
    )
    assert verdict.allowed is False
    assert "demo-app/app/api" in verdict.reasons[0]


def test_a_new_file_is_attributed_by_directory():
    verdict = review(
        [{"path": "demo-app/app/claims/filter.tsx", "content": "x"}],
        allowed_modules=["demo-app/app/claims"],
        known_modules=KNOWN,
    )
    assert verdict.allowed is True


def test_python_that_does_not_parse_is_refused():
    verdict = review([{"path": "a.py", "content": "def broken(:"}])
    assert verdict.allowed is False and "does not parse" in verdict.reasons[0]


def test_valid_python_passes():
    assert review([{"path": "a.py", "content": "def ok():\n    return 1\n"}]).allowed


@pytest.mark.parametrize(
    "path",
    [".github/workflows/deploy.yml", "../outside.py", "/etc/passwd", "app/.env", "a/id_rsa"],
)
def test_paths_the_pipeline_must_never_write(path):
    assert review([{"path": path, "content": "x"}]).allowed is False


def test_a_sprawling_change_is_refused():
    edits = [{"path": f"src/f{i}.txt", "content": "x"} for i in range(MAX_FILES + 1)]
    assert "more than" in review(edits).reasons[0]


def test_an_enormous_file_is_refused():
    assert review([{"path": "a.txt", "content": "x" * 200_000}]).allowed is False


def test_a_path_no_module_owns_is_refused_not_silently_dropped():
    """The bypass this exists to catch. An unmapped path used to be dropped
    from `touched`, and the containment check ran only `if touched` — so a
    change made entirely of paths the graph could not place skipped the check
    altogether and was allowed. Demonstrated with exactly that shape."""
    known = {"demo-app/app/claims": {"demo-app/app/claims/page.tsx"}}

    verdict = review(
        [{"path": "totally/elsewhere/backdoor.ts", "content": "x"}],
        allowed_modules=["demo-app/app/claims"],
        known_modules=known,
    )

    assert verdict.allowed is False
    assert "containment cannot be checked" in verdict.reasons[0]
    assert "totally/elsewhere/backdoor.ts" in verdict.reasons[0]


def test_one_unmapped_path_among_valid_ones_is_still_refused():
    """The mixed case is the more likely one: a change that mostly stays put
    and adds one file somewhere nobody expected."""
    known = {"demo-app/app/claims": {"demo-app/app/claims/page.tsx"}}

    verdict = review(
        [
            {"path": "demo-app/app/claims/page.tsx", "content": "x"},
            {"path": "totally/elsewhere/backdoor.ts", "content": "x"},
        ],
        allowed_modules=["demo-app/app/claims"],
        known_modules=known,
    )

    assert verdict.allowed is False
    assert any("containment cannot be checked" in r for r in verdict.reasons)


def test_a_new_file_inside_an_allowed_module_is_still_allowed():
    """Attribution by directory is what keeps the fix from refusing every new
    file: the graph has no row for it, but its module is unambiguous."""
    known = {"demo-app/app/claims": {"demo-app/app/claims/page.tsx"}}

    verdict = review(
        [{"path": "demo-app/app/claims/StatusFilter.tsx", "content": "export const x = 1\n"}],
        allowed_modules=["demo-app/app/claims"],
        known_modules=known,
    )

    assert verdict.allowed is True
    assert verdict.modules == ["demo-app/app/claims"]


def test_proposing_nothing_is_refused():
    assert review([]).reasons == ["the agent proposed no file changes"]


# --- the phase in the graph ------------------------------------------------


async def _graph(llm=None, source_control=None, graph_store=None):
    logger = AuditLogger(InMemoryAuditSink())
    # Seeded, because design now fails closed on an empty graph.
    store = graph_store or await seeded_graph()
    nodes = build_nodes(
        requirements_source=StubRequirementsSource(),
        code_design_context=StubCodeDesignContext(),
        test_management=StubTestManagement(),
        build_deploy=StubBuildDeploy(),
        work_dispatch=StubWorkDispatch(SUCCESS),
        source_control=source_control or StubSourceControl(),
        dispatch_store=InMemoryDispatchStore(),
        context_graph=store,
        llm_provider=llm or WritingLLMProvider(),
        audit_logger=logger,
        gate_controller=GateController(logger),
        max_retries=1,
    )
    return build_graph(nodes, checkpointer=MemorySaver())


async def _to_implementation(graph, run_id):
    thread = {"configurable": {"thread_id": run_id}}
    await graph.ainvoke(
        {"run_id": run_id,
         "config": PipelineConfig(auto_approve_gates=False, max_node_retries=1),
         "raw_input": {"text": "add a status filter", "file_bytes": None, "filename": None}},
        config=thread,
    )
    await graph.ainvoke(Command(resume={"approved": True}), config=thread)
    return await graph.ainvoke(Command(resume={"approved": True}), config=thread)


@pytest.mark.asyncio
async def test_a_proposed_change_reaches_qa_with_its_files():
    source = StubSourceControl()
    result = await _to_implementation(await _graph(source_control=source), "impl-1")

    assert result["status"] == "awaiting_qa_execution"
    assert result["implementation"]["files"] == ["demo-app/app/claims/page.tsx"]
    assert result["implementation"]["url"].startswith("https://stub/pull/")
    assert source.opened[0]["branch"].startswith("agentic/")


@pytest.mark.asyncio
async def test_what_changed_is_carried_into_the_qa_dispatch():
    """The whole point of implementing before testing: QA scopes to what the
    change actually touched rather than to the whole application."""
    result = await _to_implementation(await _graph(), "impl-2")
    assert result["changed_paths"] == ["demo-app/app/claims/page.tsx"]


@pytest.mark.asyncio
async def test_a_blocked_agent_stops_the_run_instead_of_guessing():
    graph = await _graph(llm=WritingLLMProvider(blocked="the criteria need a new endpoint"))
    result = await _to_implementation(graph, "impl-3")

    assert result["status"] == "implementation_blocked"
    assert "new endpoint" in result["implementation"]["blocked"]


@pytest.mark.asyncio
async def test_a_blocked_run_never_reaches_qa_or_a_release():
    graph = await _graph(llm=WritingLLMProvider(blocked="cannot be done here"))
    result = await _to_implementation(graph, "impl-4")

    assert "__interrupt__" not in result
    assert result.get("qa_result") is None
    assert result.get("release") is None


@pytest.mark.asyncio
async def test_a_change_outside_the_design_is_refused_and_nothing_is_opened():
    """The design names a file it is allowed to touch; the implementation
    writes somewhere else entirely. That disagreement is the only case
    containment exists for."""
    source = StubSourceControl(files={"demo-app/app/claims/page.tsx": "x"})
    graph = await _graph(
        llm=WritingLLMProvider(implementation_path="somewhere/else/file.ts"),
        source_control=source,
    )

    result = await _to_implementation(graph, "impl-5")

    assert result["status"] == "implementation_rejected"
    assert source.opened == []


@pytest.mark.asyncio
async def test_the_mock_provider_refuses_to_write_code():
    """A mock that invented file edits would let this phase appear to work
    with no model behind it, which is the one thing a mock must never do."""
    from app.adapters.llm.mock_adapter import MockLLMProvider
    from app.agents.implementation import Implementation

    result = await MockLLMProvider().complete_json("s", "u", Implementation)

    assert result.edits == []
    assert "cannot write code" in result.blocked


@pytest.mark.asyncio
async def test_the_revision_pair_reaches_the_dispatch():
    """The chain that was broken end to end: the implementation phase opens a
    change, and the QA dispatch is told which two commits to diff. Both keys
    were read by the dispatch node and written by nothing."""
    graph = await _graph()
    result = await _to_implementation(graph, "impl-rev-1")

    assert result["status"] == "awaiting_qa_execution"
    assert result["base_sha"] == "cafe0000"
    assert result["head_sha"] == "deadbeef"
    assert result["implementation"]["base_commit"] == "cafe0000"


@pytest.mark.asyncio
async def test_a_run_with_no_commit_to_test_is_failed_not_dispatched():
    """An executor handed no revision checks out its own default branch and
    reports a verdict on code the run never touched — which reads exactly
    like a passing QA result."""
    source = StubSourceControl(commit=None)
    graph = await _graph(source_control=source)

    result = await _to_implementation(graph, "impl-rev-2")

    assert result["status"] == "qa_failed"
    assert "no commit to test" in result["qa_result"]["reasons"][0]


@pytest.mark.asyncio
async def test_a_refused_change_never_reaches_the_qa_phase():
    """Routing used to key on whether the proposal named any files — and the
    rejected branch reports the files it refused, so refusals were routed
    onward like accepted changes."""
    source = StubSourceControl(files={"demo-app/app/claims/page.tsx": "x"})
    graph = await _graph(
        llm=WritingLLMProvider(implementation_path="somewhere/else/file.ts"),
        source_control=source,
    )

    result = await _to_implementation(graph, "impl-rev-3")

    assert result["status"] == "implementation_rejected"
    assert "qa_result" not in result
