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


def test_proposing_nothing_is_refused():
    assert review([]).reasons == ["the agent proposed no file changes"]


# --- the phase in the graph ------------------------------------------------


def _graph(llm=None, source_control=None, graph_store=None):
    logger = AuditLogger(InMemoryAuditSink())
    store = graph_store or InMemoryContextGraph()
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
    result = await _to_implementation(_graph(source_control=source), "impl-1")

    assert result["status"] == "awaiting_qa_execution"
    assert result["implementation"]["files"] == ["demo-app/app/claims/page.tsx"]
    assert result["implementation"]["url"].startswith("https://stub/pull/")
    assert source.opened[0]["branch"].startswith("agentic/")


@pytest.mark.asyncio
async def test_what_changed_is_carried_into_the_qa_dispatch():
    """The whole point of implementing before testing: QA scopes to what the
    change actually touched rather than to the whole application."""
    result = await _to_implementation(_graph(), "impl-2")
    assert result["changed_paths"] == ["demo-app/app/claims/page.tsx"]


@pytest.mark.asyncio
async def test_a_blocked_agent_stops_the_run_instead_of_guessing():
    graph = _graph(llm=WritingLLMProvider(blocked="the criteria need a new endpoint"))
    result = await _to_implementation(graph, "impl-3")

    assert result["status"] == "implementation_blocked"
    assert "new endpoint" in result["implementation"]["blocked"]


@pytest.mark.asyncio
async def test_a_blocked_run_never_reaches_qa_or_a_release():
    graph = _graph(llm=WritingLLMProvider(blocked="cannot be done here"))
    result = await _to_implementation(graph, "impl-4")

    assert "__interrupt__" not in result
    assert result.get("qa_result") is None
    assert result.get("release") is None


@pytest.mark.asyncio
async def test_a_change_outside_the_design_is_refused_and_nothing_is_opened():
    store = InMemoryContextGraph()
    source = StubSourceControl(files={"demo-app/app/api/claims/route.ts": "x"})
    graph = _graph(llm=WritingLLMProvider(path="somewhere/else/file.ts"), source_control=source,
                   graph_store=store)

    result = await _to_implementation(graph, "impl-5")

    assert result["status"] in ("implementation_rejected", "awaiting_qa_execution")
    if result["status"] == "implementation_rejected":
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
