"""Substituting a client's agent for one of this platform's own.

The default implementations stay local — they are the ones whose behaviour
is known here. What the port buys is that a client's agent is a
configuration change rather than a fork, and that whatever it returns is
judged by exactly the same deterministic review.

Two shapes have to fit one contract because they differ in latency by four
orders of magnitude: an in-process call answers in seconds, a client's cloud
agent is dispatched and answers an hour later. The phase branches on the
outcome rather than on which adapter is configured, so adding an agent does
not add a branch to the phase.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.ports.design_agent import DesignOutcome, DesignProposal, DesignRequest


IN_SCOPE = DesignProposal(
    summary="add a status filter",
    rationale="the criterion is about the claims list, which this module owns",
    modules=["demo-app/app/claims"],
    files=["demo-app/app/claims/page.tsx"],
)


class _SynchronousAgent:
    """A client agent that answers in-process, like the default does."""

    def __init__(self, proposal: DesignProposal) -> None:
        self.proposal = proposal
        self.requests: list[DesignRequest] = []

    async def propose(self, request: DesignRequest) -> DesignOutcome:
        self.requests.append(request)
        return DesignOutcome(state="ready", proposal=self.proposal)

    def read_result(self, payload: dict[str, Any]) -> DesignProposal:
        raise NotImplementedError


class _DispatchedAgent:
    """A client agent that works elsewhere and answers into a payload."""

    def __init__(self, proposal: DesignProposal) -> None:
        self.proposal = proposal
        self.started = 0

    async def propose(self, request: DesignRequest) -> DesignOutcome:
        self.started += 1
        return DesignOutcome(
            state="pending",
            provider="client-agent",
            dispatch_inputs={"prompt": request.requirement},
        )

    def read_result(self, payload: dict[str, Any]) -> DesignProposal:
        return DesignProposal(**payload["design"])


async def _run_design(agent, *, dispatch_state: str = "succeeded", payload=None):
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

    logger = AuditLogger(InMemoryAuditSink())
    gate = GateController(logger)

    async def _answer(_state, _phase, _payload):
        return {"state": dispatch_state, "payload": payload or {}}

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
        source_control=StubSourceControl(),
        audit_logger=logger,
        gate_controller=gate,
        design_agent=agent,
        design_dispatch=StubWorkDispatch(),
        max_retries=1,
    )
    return await nodes["design_proposal"]({
        "run_id": "run-1",
        "raw_input": {"text": "add a status filter to the claims list"},
    })


# --- the default is unchanged ----------------------------------------------


@pytest.mark.asyncio
async def test_the_phase_uses_this_platforms_agent_when_none_is_supplied():
    """The default stays local. A client substitutes; nobody has to opt in to
    the shipped behaviour."""
    from app.agents.nodes import build_nodes
    from app.core.audit import AuditLogger
    from app.core.gate_controller import GateController
    from tests.dispatch_doubles import InMemoryDispatchStore, StubWorkDispatch
    from tests.graph_doubles import seeded_graph
    from tests.implementation_doubles import StubSourceControl, WritingLLMProvider
    from tests.test_graph_runtime import (
        InMemoryAuditSink, StubBuildDeploy, StubCodeDesignContext,
        StubRequirementsSource, StubTestManagement,
    )

    logger = AuditLogger(InMemoryAuditSink())
    nodes = build_nodes(
        requirements_source=StubRequirementsSource(),
        code_design_context=StubCodeDesignContext(),
        test_management=StubTestManagement(),
        build_deploy=StubBuildDeploy(),
        work_dispatch=StubWorkDispatch(),
        dispatch_store=InMemoryDispatchStore(),
        context_graph=await seeded_graph(),
        llm_provider=WritingLLMProvider(),
        source_control=StubSourceControl(),
        audit_logger=logger,
        gate_controller=GateController(logger),
        max_retries=1,
    )
    result = await nodes["design_proposal"]({
        "run_id": "run-1", "raw_input": {"text": "add a status filter"},
    })
    assert result["status"] == "awaiting_gate_2"


# --- a synchronous client agent --------------------------------------------


@pytest.mark.asyncio
async def test_a_client_agent_is_given_the_catalogue_rather_than_the_repository():
    """Assembled by the phase, not fetched by the adapter, so a client's agent
    chooses from modules the graph has and cannot quietly widen what it looks
    at."""
    agent = _SynchronousAgent(IN_SCOPE)
    await _run_design(agent)

    request = agent.requests[0]
    assert [entry["id"] for entry in request.catalogue] == ["demo-app/app/claims"]
    assert request.max_files > 0


@pytest.mark.asyncio
async def test_a_client_agents_proposal_is_reviewed_exactly_as_strictly():
    """The point of the port. Substituting the agent does not substitute the
    review — and a client's agent is the only one that can change without
    anyone here knowing."""
    agent = _SynchronousAgent(
        IN_SCOPE.model_copy(update={"files": ["infrastructure/main.tf"],
                                    "modules": ["infrastructure"]})
    )
    result = await _run_design(agent)

    assert result["status"] == "design_rejected"
    assert any("unknown module" in r for r in result["design_proposal"]["rejected"])


@pytest.mark.asyncio
async def test_a_client_agent_that_declines_is_a_useful_answer():
    agent = _SynchronousAgent(DesignProposal(blocked="the requirement needs a new service"))
    result = await _run_design(agent)

    assert result["status"] == "design_blocked"
    assert "new service" in result["design_proposal"]["blocked"]


@pytest.mark.asyncio
async def test_a_rejected_proposal_is_fed_back_for_another_attempt():
    class _LearnsOnce(_SynchronousAgent):
        async def propose(self, request):
            self.requests.append(request)
            if request.rejected_reasons:
                return DesignOutcome(state="ready", proposal=IN_SCOPE)
            return DesignOutcome(
                state="ready",
                proposal=IN_SCOPE.model_copy(update={"modules": ["nope"]}),
            )

    agent = _LearnsOnce(IN_SCOPE)
    result = await _run_design(agent)

    assert result["status"] == "awaiting_gate_2"
    assert agent.requests[1].rejected_reasons


# --- a dispatched client agent ---------------------------------------------


@pytest.mark.asyncio
async def test_a_dispatched_agent_parks_and_its_answer_is_reviewed():
    """An hour-long design on the same seam CI uses, so it survives a
    restart."""
    agent = _DispatchedAgent(IN_SCOPE)
    result = await _run_design(agent, payload={"design": IN_SCOPE.model_dump()})

    assert agent.started == 1
    assert result["status"] == "awaiting_gate_2"
    assert result["design_proposal"]["modules"] == ["demo-app/app/claims"]


@pytest.mark.asyncio
async def test_a_dispatched_agent_out_of_scope_is_refused_like_any_other():
    agent = _DispatchedAgent(IN_SCOPE)
    result = await _run_design(
        agent,
        payload={"design": IN_SCOPE.model_copy(update={"modules": ["infrastructure"]}).model_dump()},
    )

    assert result["status"] == "design_rejected"


@pytest.mark.asyncio
async def test_a_dispatch_that_fails_does_not_produce_a_design():
    agent = _DispatchedAgent(IN_SCOPE)
    result = await _run_design(agent, dispatch_state="failed")

    assert result["status"] == "design_rejected"
    assert "produced nothing" in result["design_proposal"]["failed"]


@pytest.mark.asyncio
async def test_a_dispatched_agent_is_not_asked_twice():
    """A retry would mean a second agent run. The reasons a human needs are
    better read on the rejected proposal than burned on another dispatch."""
    agent = _DispatchedAgent(IN_SCOPE)
    await _run_design(
        agent,
        payload={"design": IN_SCOPE.model_copy(update={"modules": ["nope"]}).model_dump()},
    )

    assert agent.started == 1


# --- the derived half stays ours -------------------------------------------


@pytest.mark.asyncio
async def test_the_impact_set_is_derived_here_whoever_proposed_the_design():
    """An architect can be wrong about consequences, and a client's architect
    is no different. The impact set comes from the graph either way."""
    agent = _SynchronousAgent(IN_SCOPE)
    result = await _run_design(agent)

    assert "impact" in result["design_proposal"]
    assert set(result["design_proposal"]["impact"]) == {"files", "modules"}
