"""The agent seam that had no port.

A client's coding agent was selected by a setting and bound straight to
WorkDispatch, so "implement this" travelled as
`{"prompt": str, "base_ref": str, "repo": str}` — an untyped dict through a
port whose vocabulary is CI jobs. DesignAgent, the other agent-substitution
point, had a typed façade. The two were modelled two different ways for no
reason anyone had decided.
"""

from __future__ import annotations

import pytest

from app.adapters.implementation_agent.dispatched import DispatchedImplementationAgent
from app.adapters.implementation_agent.inline import InlineImplementationAgent
from app.ports.implementation_agent import (
    ImplementationRequest,
    ImplementationResult,
)


class FakeLLM:
    def __init__(self, proposal):
        self.proposal = proposal
        self.seen = None

    async def complete_json(self, system, prompt, schema):
        self.seen = prompt
        return self.proposal


class Proposal:
    def __init__(self, edits, blocked=""):
        self.summary = "did the thing"
        self.edits = edits
        self.blocked = blocked


class Edit:
    def __init__(self, path, content):
        self.path, self.content = path, content


def inline(proposal):
    return InlineImplementationAgent(
        llm_provider=FakeLLM(proposal),
        system_prompt="sys",
        schema=object,
        build_prompt=lambda **kw: str(sorted(kw)),
    )


# ── both arms answer the same shape ───────────────────────────────────────


@pytest.mark.asyncio
async def test_the_inline_agent_answers_immediately_with_its_edits():
    """Nothing is written anywhere until the change has been reviewed. That
    ordering is the difference between the two arms: the client's agent
    pushes a branch and is judged after the fact."""
    agent = inline(Proposal([Edit("a.ts", "x")]))
    out = await agent.implement(ImplementationRequest(run_id="r1"))

    assert out.state == "ready"
    assert out.result.files == ["a.ts"]
    assert out.result.edits[0].content == "x"


@pytest.mark.asyncio
async def test_a_refusal_is_an_answer_not_a_failure():
    agent = inline(Proposal([], blocked="the design names a file that does not exist"))
    out = await agent.implement(ImplementationRequest(run_id="r1"))

    assert out.state == "ready"
    assert out.result.blocked
    assert out.result.edits == []


@pytest.mark.asyncio
async def test_the_dispatched_agent_returns_a_receipt_not_a_result():
    agent = DispatchedImplementationAgent("github-copilot", dispatch=None)
    out = await agent.implement(
        ImplementationRequest(run_id="r1", brief="do the thing", repo="acme/x", base_ref="main")
    )

    assert out.state == "pending"
    assert out.provider == "github-copilot"
    assert out.result is None


@pytest.mark.asyncio
async def test_the_adapter_describes_the_work_and_the_phase_starts_it():
    """An adapter that triggered on its own would be starting remote work the
    platform has no dispatch row for, and a crash between the two would leave
    an agent running that nothing is waiting on."""
    agent = DispatchedImplementationAgent("github-copilot", dispatch=None)
    out = await agent.implement(
        ImplementationRequest(run_id="r1", brief="brief text", repo="acme/x", base_ref="main")
    )
    assert out.dispatch_inputs == {
        "prompt": "brief text",
        "base_ref": "main",
        "repo": "acme/x",
    }


# ── the reconciler-safe half ──────────────────────────────────────────────


def test_read_result_interprets_a_payload_without_the_state_that_started_it():
    """A two-hour agent run is resumed after a restart with nothing but this
    payload, which is why interpreting it is a separate method."""
    agent = DispatchedImplementationAgent("github-copilot", dispatch=None)
    finished = agent.read_result(
        {
            "head_ref": "copilot/fix-1",
            "base_ref": "main",
            "head_sha": "abc123",
            "base_sha": "def456",
            "external_url": "https://github.com/acme/x/pull/7",
            "pull_request_id": 7,
        }
    )
    assert finished.head_ref == "copilot/fix-1"
    assert finished.head_sha == "abc123"
    assert finished.url.endswith("/pull/7")
    assert finished.pull_request_id == "7"


def test_a_payload_naming_no_branch_yields_nothing_to_review():
    """Without head_ref there is no branch to diff, so the change cannot be
    checked against the design at all — the phase fails rather than
    proceeding on the agent's word."""
    agent = DispatchedImplementationAgent("github-copilot", dispatch=None)
    assert agent.read_result({}).head_ref == ""


def test_the_inline_agent_never_has_read_result_called():
    with pytest.raises(NotImplementedError):
        inline(Proposal([])).read_result({})


# ── capabilities are declared, not discovered ─────────────────────────────


@pytest.mark.parametrize(
    "agent,dispatched",
    [
        (inline(Proposal([])), False),
        (DispatchedImplementationAgent("github-copilot", dispatch=None), True),
    ],
)
def test_every_agent_declares_whether_it_parks(agent, dispatched):
    assert agent.capabilities()["dispatched"] is dispatched
    assert agent.contract_version >= 1


def test_neither_agent_claims_to_honour_the_scope_it_is_given():
    """The constraint is enforced by the review, not by the agent's good
    intentions. Claiming otherwise would assert a guarantee only containment
    provides."""
    for agent in (inline(Proposal([])), DispatchedImplementationAgent("x", None)):
        assert agent.capabilities()["honours_allowed_files"] is False


@pytest.mark.asyncio
async def test_check_access_is_a_declared_capability_not_a_getattr_probe():
    class Reachable:
        async def check_access(self):
            return {"ok": True, "detail": "authenticated"}

    agent = DispatchedImplementationAgent("github-copilot", dispatch=Reachable())
    assert (await agent.check_access())["ok"] is True

    bare = DispatchedImplementationAgent("github-copilot", dispatch=object())
    assert (await bare.check_access())["ok"] is False
