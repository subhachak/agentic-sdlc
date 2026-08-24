"""Proves the interrupt/resume mechanics from the gate controller against the
real linear graph and a real LangGraph checkpointer (MemorySaver — same
BaseCheckpointSaver contract as the SQLite checkpointer used at runtime;
swapping backends doesn't change these mechanics).
"""

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from app.agents.graph import build_graph
from app.agents.nodes import build_nodes
from app.agents.state import PipelineConfig
from app.core.audit import AuditLogger
from app.core.gate_controller import GateController
from app.ports.audit_sink import AuditEntry
from app.ports.build_deploy import BuildResult
from app.ports.code_design_context import ContextSnippet
from app.ports.requirements_source import RequirementsDoc
from app.ports.test_management import TestCaseRecord
from tests.graph_doubles import InMemoryContextGraph
from tests.implementation_doubles import StubSourceControl, WritingLLMProvider
from tests.dispatch_doubles import SUCCESS, InMemoryDispatchStore, StubWorkDispatch


class InMemoryAuditSink:
    def __init__(self) -> None:
        self.entries: list[AuditEntry] = []

    async def write(self, entry: AuditEntry) -> None:
        self.entries.append(entry)

    async def query(self, run_id: str) -> list[AuditEntry]:
        return [e for e in self.entries if e.run_id == run_id]


class StubRequirementsSource:
    async def fetch(self, raw):
        return RequirementsDoc(text=raw.text or "", source_type="text", item_count=1)


class StubCodeDesignContext:
    async def retrieve_context(self, query: str, top_k: int = 3):
        return [ContextSnippet(doc_id="d1", title="Doc", text="stub", score=0.5)]


class StubTestManagement:
    def __init__(self) -> None:
        self.created: list[TestCaseRecord] = []

    async def create_test_case(self, run_id: str, tc: TestCaseRecord) -> TestCaseRecord:
        self.created.append(tc)
        return tc

    async def list_test_cases(self, run_id: str) -> list[TestCaseRecord]:
        return [t for t in self.created if t.run_id == run_id]


class StubBuildDeploy:
    async def trigger_build(self, run_id: str, payload: dict):
        return BuildResult(success=True, build_id="build-1", message="ok")


class StubLLMProvider:
    async def complete(self, system_prompt: str, user_prompt: str, *, max_tokens: int = 1024):
        raise AssertionError("stub node logic must not call the LLM in this phase")


def _build_test_graph(work_dispatch=None, dispatch_store=None, llm=None, source_control=None):
    sink = InMemoryAuditSink()
    logger = AuditLogger(sink)
    gate_controller = GateController(logger)
    work_dispatch = work_dispatch or StubWorkDispatch(SUCCESS)
    dispatch_store = dispatch_store if dispatch_store is not None else InMemoryDispatchStore()
    nodes = build_nodes(
        requirements_source=StubRequirementsSource(),
        code_design_context=StubCodeDesignContext(),
        test_management=StubTestManagement(),
        build_deploy=StubBuildDeploy(),
        work_dispatch=work_dispatch,
        dispatch_store=dispatch_store,
        context_graph=InMemoryContextGraph(),
        llm_provider=llm or WritingLLMProvider(),
        source_control=source_control or StubSourceControl(),
        audit_logger=logger,
        gate_controller=gate_controller,
        max_retries=1,
    )
    graph = build_graph(nodes, checkpointer=MemorySaver())
    return graph, sink


def _initial_state(run_id: str, *, auto_approve: bool = False) -> dict:
    return {
        "run_id": run_id,
        "config": PipelineConfig(auto_approve_gates=auto_approve, max_node_retries=1),
        "raw_input": {"text": "As a user I want to log in", "file_bytes": None, "filename": None},
    }


@pytest.mark.asyncio
async def test_pipeline_pauses_at_three_gates_and_completes_on_approval():
    graph, sink = _build_test_graph()
    run_id = "test-run-1"
    thread = {"configurable": {"thread_id": run_id}}

    result = await graph.ainvoke(_initial_state(run_id), config=thread)
    assert "__interrupt__" in result
    assert result["status"] == "awaiting_gate_1"

    result = await graph.ainvoke(Command(resume={"approved": True}), config=thread)
    assert "__interrupt__" in result
    assert result["status"] == "awaiting_gate_2"

    # Approving gate 2 now runs the implementation phase and then hands the QA
    # phase to a remote executor, so the graph parks on the machine pause
    # rather than going straight to gate 3.
    result = await graph.ainvoke(Command(resume={"approved": True}), config=thread)
    assert "__interrupt__" in result
    assert result["status"] == "awaiting_qa_execution"

    result = await graph.ainvoke(
        Command(resume={"state": "succeeded", "payload": {"gate_passed": True}}), config=thread
    )
    assert "__interrupt__" in result
    assert result["status"] == "awaiting_gate_3"

    result = await graph.ainvoke(Command(resume={"approved": True}), config=thread)
    assert "__interrupt__" not in result
    assert result["status"] == "completed"
    assert result["build_result"]["success"] is True

    # Exactly one before + one after per gate, despite each gate node
    # re-executing from its start on the resume pass (see GateController's
    # has_written dedupe guard).
    for gate_name in ("gate_1", "gate_2", "gate_3"):
        gate_entries = [e for e in sink.entries if e.node_name == gate_name]
        assert [e.phase for e in gate_entries] == ["before", "after"], gate_entries
        assert gate_entries[0].confirmed is False
        assert gate_entries[1].human_decision == "approved"


@pytest.mark.asyncio
async def test_rejection_at_gate_halts_pipeline_instead_of_continuing():
    graph, _sink = _build_test_graph()
    run_id = "test-run-2"
    thread = {"configurable": {"thread_id": run_id}}

    await graph.ainvoke(_initial_state(run_id), config=thread)
    result = await graph.ainvoke(
        Command(resume={"approved": False, "feedback": "not ready"}), config=thread
    )
    assert "__interrupt__" not in result
    assert result["status"] == "rejected_at_gate_1"
    assert "design_proposal" not in result or result.get("design_proposal") is None


@pytest.mark.asyncio
async def test_auto_approve_skips_human_gates_but_never_the_machine_one():
    """auto_approve_gates exists so a headless run does not stop for a
    person. It cannot manufacture the result of a job that has not run, so
    qa_execution still parks — and that is the only pause left."""
    graph, sink = _build_test_graph()
    run_id = "test-run-3"
    thread = {"configurable": {"thread_id": run_id}}

    result = await graph.ainvoke(_initial_state(run_id, auto_approve=True), config=thread)
    assert "__interrupt__" in result
    assert result["status"] == "awaiting_qa_execution"

    result = await graph.ainvoke(
        Command(resume={"state": "succeeded", "payload": {"gate_passed": True}}), config=thread
    )
    assert "__interrupt__" not in result
    assert result["status"] == "completed"

    gate_entries = [e for e in sink.entries if e.node_name in ("gate_1", "gate_2", "gate_3")]
    assert len(gate_entries) == 6
    assert all(e.human_decision == "approved" for e in gate_entries if e.phase == "after")
