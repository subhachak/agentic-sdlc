"""Handing the implementation to an agent this platform does not run.

The governance question is not whether a client's cloud agent can be used.
It is what happens when it does something the design did not sanction — and
the answer has to be different from the in-process case, because an agent
working elsewhere opens its own branch and cannot be refused before it
writes. Containment there is detection, and these pin that it detects.
"""

from __future__ import annotations

import json

import pytest

from app.adapters.work_dispatch.github_copilot import (
    GitHubCopilotWorkDispatch,
    artifacts_of,
    _result_from,
)
from app.agents.handoff import build_task
from app.ports.work_dispatch import DispatchHandle


DESIGN = {
    "summary": "add a date filter",
    "rationale": "the criterion is about the claims list",
    "modules": ["demo-app/app/claims"],
    "files": ["demo-app/app/claims/page.tsx"],
    "criteria_addressed": ["ac-1"],
}


# --- the task statement ----------------------------------------------------


def test_the_task_names_the_files_and_the_modules_it_may_not_leave():
    """An in-process agent is refused if it returns the wrong shape. This one
    gets prose, so the constraint has to be in the prose."""
    task = build_task(
        requirement="Add a date filter",
        design=DESIGN,
        criteria=[{"id": "ac-1", "text": "The list can be filtered by date"}],
        run_id="abc123",
    )

    assert "demo-app/app/claims/page.tsx" in task
    assert "demo-app/app/claims" in task
    assert "refused" in task
    assert "ac-1" in task


def test_the_task_says_widening_scope_will_be_refused():
    """It changes what a competent agent does with an ambiguous instruction:
    being helpful by touching one more file is the specific behaviour that
    gets the work rejected."""
    task = build_task(requirement="x", design=DESIGN, criteria=[], run_id="r")

    assert "rather than widening the scope" in task
    assert "checked against this list" in task


def test_a_design_naming_nothing_still_produces_a_usable_statement():
    task = build_task(requirement="x", design={}, criteria=[], run_id="r")
    assert "the design named no files" in task


# --- reading the provider's answer -----------------------------------------


def _handle() -> DispatchHandle:
    return DispatchHandle(provider="github-copilot", correlation_id="n", external_id="t1")


def _task(state: str, artifacts: list | None = None) -> dict:
    return {"id": "t1", "state": state, "html_url": "https://github.com/x/y/tasks/t1",
            "artifacts": artifacts or []}


@pytest.mark.parametrize("state", ["queued", "in_progress"])
def test_a_running_task_is_pending(state):
    assert _result_from(_task(state), _handle()).state == "pending"


@pytest.mark.parametrize("state", ["idle", "waiting_for_user"])
def test_an_agent_waiting_for_a_person_is_pending_and_says_so(state):
    """Not progress and not failure. "Still running" and "waiting for you"
    call for different responses from whoever is watching, and the deadline
    ledger decides either way."""
    result = _result_from(_task(state), _handle())

    assert result.state == "pending"
    assert "waiting for input" in result.detail


@pytest.mark.parametrize("state,expected", [
    ("failed", "failed"), ("cancelled", "failed"), ("timed_out", "timed_out"),
])
def test_terminal_failures_are_reported_as_such(state, expected):
    assert _result_from(_task(state), _handle()).state == expected


def test_a_completed_task_returns_the_branch_it_produced():
    result = _result_from(
        _task("completed", [
            {"provider": "github", "type": "branch",
             "data": {"head_ref": "copilot/fix-1", "base_ref": "main"}},
            {"provider": "github", "type": "pull", "data": {"id": 42, "global_id": "PR_x"}},
        ]),
        _handle(),
    )

    assert result.state == "succeeded"
    assert result.payload["head_ref"] == "copilot/fix-1"
    assert result.payload["base_ref"] == "main"
    assert result.payload["pull_request_id"] == 42


def test_a_completed_task_with_no_branch_is_a_failure():
    """There is nothing to review. Treating it as success would send an empty
    change to QA, which would pass and prove nothing."""
    result = _result_from(_task("completed"), _handle())

    assert result.state == "failed"
    assert "without producing a branch" in result.detail


def test_an_unrecognised_state_fails_rather_than_being_assumed_benign():
    """The provider may add states. Guessing that a new one means success is
    the one guess that ships an unreviewed change."""
    assert _result_from(_task("garden_leave"), _handle()).state == "failed"


def test_artifacts_are_picked_out_by_type_not_by_position():
    artifacts = artifacts_of(_task("completed", [
        {"provider": "github", "type": "pull", "data": {"id": 7}},
        {"provider": "github", "type": "branch", "data": {"head_ref": "b", "base_ref": "main"}},
    ]))

    assert artifacts == {"pull_request_id": 7, "head_ref": "b", "base_ref": "main"}


@pytest.mark.asyncio
async def test_a_task_that_was_never_started_is_not_polled_forever():
    """Unlike workflow_dispatch there is no correlation search to fall back
    on: the POST returns the id, so its absence means the trigger failed."""
    dispatcher = GitHubCopilotWorkDispatch(repo="acme/thing", token="t")
    result = await dispatcher.check(
        DispatchHandle(provider="github-copilot", correlation_id="n")
    )

    assert result.state == "failed"
    assert "never started" in result.detail


@pytest.mark.asyncio
async def test_an_empty_prompt_is_refused_before_anything_is_started():
    dispatcher = GitHubCopilotWorkDispatch(repo="acme/thing", token="t")

    with pytest.raises(ValueError, match="no task description"):
        await dispatcher.trigger("run-1", "implementation", "n", {"prompt": "  "})


@pytest.mark.asyncio
async def test_a_dispatch_naming_another_repository_is_refused():
    """check() polls the task under the configured repository and cannot see
    the trigger's inputs, so a task started somewhere else would come back as
    one that no longer exists — a misconfiguration wearing the disguise of a
    deleted task."""
    dispatcher = GitHubCopilotWorkDispatch(repo="acme/thing", token="t")

    with pytest.raises(ValueError, match="started in one repository"):
        await dispatcher.trigger(
            "run-1", "implementation", "n", {"prompt": "do the thing", "repo": "acme/other"}
        )



# --- the reconciler picks the right provider -------------------------------


@pytest.mark.asyncio
async def test_a_row_is_polled_by_the_provider_that_started_it():
    """QA may run in the client's CI while the change is written by their
    coding agent. A row started by one cannot be polled by the other — its
    external id means nothing there."""
    from app.core.reconciler import poll_pending
    from tests.dispatch_doubles import SUCCESS, InMemoryDispatchStore, StubWorkDispatch

    store = InMemoryDispatchStore()
    await store.claim("run-1", "implementation", "github-copilot", 1800)

    copilot, actions = StubWorkDispatch(SUCCESS), StubWorkDispatch(SUCCESS)
    await poll_pending({"github-copilot": copilot, "github-actions": actions}, store)

    assert copilot.checked
    assert not actions.checked


@pytest.mark.asyncio
async def test_a_row_whose_provider_is_gone_fails_rather_than_hanging():
    """Configuration changed under a live dispatch. Nothing here can ask a
    provider that is no longer configured how a job it started is going."""
    from app.core.reconciler import poll_pending
    from tests.dispatch_doubles import SUCCESS, InMemoryDispatchStore, StubWorkDispatch

    store = InMemoryDispatchStore()
    await store.claim("run-1", "implementation", "github-copilot", 1800)

    await poll_pending({"github-actions": StubWorkDispatch(SUCCESS)}, store)

    resolved = await store.get("run-1", "implementation")
    assert resolved.state == "failed"
    assert "no adapter configured" in resolved.detail


# --- containment on what it actually did -----------------------------------


async def _run_handoff(branch_files: dict[str, str], *, state: str = "succeeded"):
    """Drive the implementation phase with an external agent that produced
    exactly `branch_files`.

    The gate controller is stubbed to return the provider's answer directly.
    In the real graph the phase parks on an interrupt and the reconciler
    resumes it; what is under test here is what happens *after* the answer
    arrives, which is where the review lives.
    """
    from app.agents.nodes import build_nodes
    from app.core.audit import AuditLogger
    from app.core.gate_controller import GateController
    from tests.dispatch_doubles import InMemoryDispatchStore, StubWorkDispatch
    from tests.graph_doubles import seeded_graph
    from tests.implementation_doubles import StubSourceControl, WritingLLMProvider
    from tests.test_graph_runtime import (
        InMemoryAuditSink,
        StubBuildDeploy,
        StubCodeDesignContext,
        StubRequirementsSource,
        StubTestManagement,
    )

    source = StubSourceControl()
    source.branch_files = branch_files

    logger = AuditLogger(InMemoryAuditSink())
    gate = GateController(logger)

    async def _answer(_state, _phase, _payload):
        return {"state": state, "payload": {"head_ref": "copilot/fix-1", "base_ref": "main"}}

    gate.request_external = _answer  # type: ignore[assignment]

    nodes = build_nodes(
        requirements_source=StubRequirementsSource(),
        code_design_context=StubCodeDesignContext(),
        test_management=StubTestManagement(),
        build_deploy=StubBuildDeploy(),
        work_dispatch=StubWorkDispatch(),
        dispatch_store=InMemoryDispatchStore(),
        context_graph=await seeded_graph(
            module="demo-app/app/claims", paths=("demo-app/app/claims/page.tsx",)
        ),
        llm_provider=WritingLLMProvider(),
        source_control=source,
        audit_logger=logger,
        gate_controller=gate,
        implementation_agent="github-copilot",
        implementation_dispatch=StubWorkDispatch(),
        target_repo="acme/thing",
        max_retries=1,
    )

    return await nodes["implementation"]({
        "run_id": "run-1",
        "raw_input": {"text": "add a date filter"},
        "design_proposal": DESIGN,
    })


@pytest.mark.asyncio
async def test_a_change_inside_the_approved_scope_is_accepted():
    result = await _run_handoff({"demo-app/app/claims/page.tsx": "export const x = 1;\n"})

    assert result["status"] == "awaiting_qa_execution"
    assert result["implementation"]["agent"] == "github-copilot"
    assert result["implementation"]["branch"] == "copilot/fix-1"


@pytest.mark.asyncio
async def test_a_change_outside_the_approved_scope_is_refused():
    """The case the whole review exists for, and the one an external agent can
    actually produce: it worked elsewhere, so nothing stopped it writing."""
    result = await _run_handoff({
        "demo-app/app/claims/page.tsx": "export const x = 1;\n",
        "infrastructure/terraform/main.tf": "resource {}\n",
    })

    assert result["status"] == "implementation_rejected"
    assert any("containment cannot be checked" in r
               for r in result["implementation"]["rejected"])


@pytest.mark.asyncio
async def test_a_refusal_says_the_branch_still_exists():
    """The difference between the two agent shapes. An in-process agent's
    edits never reach a branch; this one's already have, and pretending
    otherwise would misrepresent what was prevented."""
    result = await _run_handoff({"totally/elsewhere/backdoor.ts": "x\n"})

    assert result["status"] == "implementation_rejected"
    assert "was not merged" in result["implementation"]["note"]
    assert result["implementation"]["branch"] == "copilot/fix-1"


@pytest.mark.asyncio
async def test_an_agent_that_produced_nothing_does_not_reach_qa():
    result = await _run_handoff({})

    assert result["status"] == "implementation_rejected"
