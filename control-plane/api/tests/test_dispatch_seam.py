"""The dispatch seam's failure modes.

Every case here is one that would otherwise be discovered in a live demo:
a duplicated CI run, a result that arrives too early, a job that never
reports. The happy path is the least interesting test in the file.
"""

import asyncio

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from app.agents.graph import build_graph
from app.agents.nodes import build_nodes
from app.agents.state import PipelineConfig
from app.core import reconciler
from app.core.audit import AuditLogger
from app.core.gate_controller import GateController
from app.core.graph_runtime import spawn_run
from app.ports.work_dispatch import DispatchResult
from tests.graph_doubles import seeded_graph
from tests.implementation_doubles import StubSourceControl, WritingLLMProvider
from tests.dispatch_doubles import (
    SUCCESS,
    ExplodingWorkDispatch,
    InMemoryDispatchStore,
    StubWorkDispatch,
)
from tests.test_graph_runtime import (
    InMemoryAuditSink,
    StubBuildDeploy,
    StubCodeDesignContext,
    StubLLMProvider,
    StubRequirementsSource,
    StubTestManagement,
)


async def _graph(work_dispatch, store):
    logger = AuditLogger(InMemoryAuditSink())
    nodes = build_nodes(
        requirements_source=StubRequirementsSource(),
        code_design_context=StubCodeDesignContext(),
        test_management=StubTestManagement(),
        build_deploy=StubBuildDeploy(),
        work_dispatch=work_dispatch,
        dispatch_store=store,
        context_graph=await seeded_graph(),
        llm_provider=WritingLLMProvider(),
        source_control=StubSourceControl(),
        audit_logger=logger,
        gate_controller=GateController(logger),
        max_retries=1,
        dispatch_timeout_seconds=1800,
    )
    return build_graph(nodes, checkpointer=MemorySaver())


async def _drive_to_qa(graph, run_id: str) -> dict:
    """Run far enough to park on qa_execution."""
    thread = {"configurable": {"thread_id": run_id}}
    await graph.ainvoke(
        {
            "run_id": run_id,
            "config": PipelineConfig(auto_approve_gates=False, max_node_retries=1),
            "raw_input": {"text": "a requirement", "file_bytes": None, "filename": None},
        },
        config=thread,
    )
    await graph.ainvoke(Command(resume={"approved": True}), config=thread)
    return await graph.ainvoke(Command(resume={"approved": True}), config=thread)


# --- hazard one: the resume pass must not fire a second job ----------------


@pytest.mark.asyncio
async def test_resuming_does_not_trigger_a_second_dispatch():
    """LangGraph re-executes a node from its start on resume, so the code
    before interrupt() runs twice. Without the claim guard that means a
    second workflow run: minutes burned, the data store mutated again, and a
    result nothing will ever read."""
    dispatcher, store = StubWorkDispatch(), InMemoryDispatchStore()
    graph = await _graph(dispatcher, store)

    result = await _drive_to_qa(graph, "run-a")
    assert result["status"] == "awaiting_qa_execution"
    assert len(dispatcher.triggers) == 1

    await graph.ainvoke(
        Command(resume={"state": "succeeded", "payload": {}}),
        config={"configurable": {"thread_id": "run-a"}},
    )

    assert len(dispatcher.triggers) == 1, "the resume pass triggered a second CI run"
    assert len(store.rows) == 1


@pytest.mark.asyncio
async def test_claim_is_what_stops_it(monkeypatch):
    """Same guard, isolated: a second claim for the same run and phase is
    refused, which is the unique constraint's job in the real store."""
    store = InMemoryDispatchStore()
    first = await store.claim("run-a", "qa", "stub", 60)
    second = await store.claim("run-a", "qa", "stub", 60)

    assert first is not None
    assert second is None


# --- hazard two: a result that arrives before the thread parks -------------


@pytest.mark.asyncio
async def test_a_result_is_queued_not_lost_while_the_thread_is_busy():
    """spawn_run refuses to start a second task on a busy thread. The
    reconciler must leave the row unapplied and try again, or a fast job
    would strand its run forever."""
    store = InMemoryDispatchStore()
    row = await store.claim("run-b", "qa", "stub", 60)
    await store.resolve(row.id, SUCCESS)

    busy_forever = asyncio.get_running_loop().create_future()
    active_tasks = {"run-b": asyncio.ensure_future(busy_forever)}

    applied = await reconciler.apply_results(graph=None, active_tasks=active_tasks, store=store)

    assert applied == 0
    assert (await store.list_unapplied())[0].id == row.id, "result was dropped"

    busy_forever.set_result(None)
    await asyncio.sleep(0)

    applied = await reconciler.apply_results(
        graph=await _graph(StubWorkDispatch(), store), active_tasks=active_tasks, store=store
    )
    assert applied == 1
    assert await store.list_unapplied() == []


@pytest.mark.asyncio
async def test_a_result_is_applied_only_once():
    store = InMemoryDispatchStore()
    row = await store.claim("run-c", "qa", "stub", 60)
    await store.resolve(row.id, SUCCESS)
    graph = await _graph(StubWorkDispatch(), store)

    first = await reconciler.apply_results(graph, {}, store)
    second = await reconciler.apply_results(graph, {}, store)

    assert (first, second) == (1, 0)


# --- hazard three: the job never reports -----------------------------------


@pytest.mark.asyncio
async def test_an_overdue_dispatch_times_out_instead_of_hanging():
    store = InMemoryDispatchStore()
    await store.claim("run-d", "qa", "stub", 1800)
    store.expire_all()

    resolved = await reconciler.poll_pending(StubWorkDispatch(), store)

    assert resolved == 1
    row = await store.get("run-d", "qa")
    assert row.state == "timed_out"
    assert "deadline" in row.detail


@pytest.mark.asyncio
async def test_a_timed_out_run_ends_and_never_reaches_gate_3():
    store = InMemoryDispatchStore()
    graph = await _graph(StubWorkDispatch(), store)
    await _drive_to_qa(graph, "run-e")

    result = await graph.ainvoke(
        Command(resume={"state": "timed_out", "detail": "deadline passed"}),
        config={"configurable": {"thread_id": "run-e"}},
    )

    assert result["status"] == "qa_timed_out"
    assert "gate3_decision" not in result or result.get("gate3_decision") is None


@pytest.mark.asyncio
async def test_a_failed_ci_run_ends_and_never_reaches_gate_3():
    store = InMemoryDispatchStore()
    graph = await _graph(StubWorkDispatch(), store)
    await _drive_to_qa(graph, "run-f")

    result = await graph.ainvoke(
        Command(resume={"state": "failed", "detail": "workflow concluded failure"}),
        config={"configurable": {"thread_id": "run-f"}},
    )

    assert result["status"] == "qa_failed"
    assert result.get("build_result") is None


# --- triggering that fails outright ----------------------------------------


@pytest.mark.asyncio
async def test_an_untriggerable_job_resolves_as_failed_rather_than_retrying():
    """A trigger that raises must not leave a pending row behind, or the run
    would wait out its whole deadline for a job that was never created."""
    store = InMemoryDispatchStore()
    graph = await _graph(ExplodingWorkDispatch(), store)

    await _drive_to_qa(graph, "run-g")

    row = await store.get("run-g", "qa")
    assert row.state == "failed"
    assert "could not trigger" in row.detail


# --- the happy path --------------------------------------------------------


@pytest.mark.asyncio
async def test_a_successful_run_carries_its_evidence_into_gate_3():
    store = InMemoryDispatchStore()
    graph = await _graph(StubWorkDispatch(SUCCESS), store)
    await _drive_to_qa(graph, "run-h")

    result = await graph.ainvoke(
        Command(resume=SUCCESS.model_dump()),
        config={"configurable": {"thread_id": "run-h"}},
    )

    assert result["status"] == "awaiting_gate_3"
    interrupt_payload = result["__interrupt__"][0].value
    assert interrupt_payload["type"] == "test_case_approval"
    evidence = interrupt_payload["qa_result"]["payload"]["evidence_summary"]
    assert evidence["screenshot_count"] == 2


@pytest.mark.asyncio
async def test_polling_resolves_a_finished_job():
    store = InMemoryDispatchStore()
    row = await store.claim("run-i", "qa", "stub", 600)

    assert await reconciler.poll_pending(StubWorkDispatch(), store) == 0
    assert await reconciler.poll_pending(StubWorkDispatch(SUCCESS), store) == 1

    resolved = await store.get("run-i", "qa")
    assert resolved.state == "succeeded"
    assert resolved.result_payload["gate_passed"] is True
    assert resolved.id == row.id


# --- driving a workflow that knows nothing about this platform -------------


class _FakeGitHub:
    """Just enough of the GitHub API surface to exercise check()."""

    def __init__(self, run, artifacts):
        self._run, self._artifacts = run, artifacts
        self.links = {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, **kwargs):
        if "artifacts" in url:
            return _Resp({"artifacts": self._artifacts})
        # /actions/runs/{id} returns one run; /workflows/{file}/runs returns a list.
        if "/actions/runs/" in url:
            return _Resp(self._run)
        return _Resp({"workflow_runs": [self._run]})


class _Resp:
    def __init__(self, payload):
        self._payload = payload
        self.status_code = 200

    def json(self):
        return self._payload

    def raise_for_status(self):
        return None


@pytest.mark.asyncio
async def test_a_workflow_with_no_state_artifact_still_reports_a_verdict(monkeypatch):
    """An existing CI pipeline should be governable without first being taught
    to emit our state file. The result is thinner and says so."""
    from app.adapters.work_dispatch import github_actions as gh
    from app.ports.work_dispatch import DispatchHandle

    run = {"id": 42, "status": "completed", "conclusion": "success",
           "html_url": "https://gh/run/42", "name": "frontend-e2e abc123"}
    monkeypatch.setattr(gh.httpx, "AsyncClient", lambda **kw: _FakeGitHub(run, []))

    adapter = gh.GitHubActionsWorkDispatch(repo="acme/app", token="t")
    result = await adapter.check(DispatchHandle(provider="github-actions",
                                                correlation_id="abc123", external_id="42"))

    assert result.state == "succeeded"
    assert result.payload["gate_passed"] is True
    assert result.payload["assertions"] == []
    assert "no state artifact" in result.detail


@pytest.mark.asyncio
async def test_a_failed_workflow_is_still_a_failure(monkeypatch):
    from app.adapters.work_dispatch import github_actions as gh
    from app.ports.work_dispatch import DispatchHandle

    run = {"id": 43, "status": "completed", "conclusion": "failure",
           "html_url": "https://gh/run/43", "name": "frontend-e2e abc123"}
    monkeypatch.setattr(gh.httpx, "AsyncClient", lambda **kw: _FakeGitHub(run, []))

    adapter = gh.GitHubActionsWorkDispatch(repo="acme/app", token="t")
    result = await adapter.check(DispatchHandle(provider="github-actions",
                                                correlation_id="abc123", external_id="43"))

    assert result.state == "failed"
    assert "failure" in result.detail
