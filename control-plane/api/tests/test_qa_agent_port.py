"""QA as a port, like design and implementation.

It was the last phase calling WorkDispatch directly with an untyped dict —
`{base_sha, head_sha, changed_paths, branch}`, a shape defined nowhere but
the phase that wrote it. It is also the phase with the largest contract of
the three, so it was the worst one to leave conventional.
"""

from __future__ import annotations

import pytest

from app.adapters.qa_agent.dispatched import DispatchedQAAgent
from app.adapters.qa_agent.local import LocalQAAgent
from app.ports.qa_agent import QARequest


# ── the contract that used to be a convention ─────────────────────────────


@pytest.mark.asyncio
async def test_the_invocation_contract_is_written_down():
    agent = DispatchedQAAgent("github-actions")
    out = await agent.execute(
        QARequest(
            run_id="r1",
            base_sha="aaa",
            head_sha="bbb",
            branch="agentic/x",
            repo="acme/thing",
            changed_paths=["app/a.ts"],
        )
    )
    assert out.state == "pending"
    assert out.dispatch_inputs["base_sha"] == "aaa"
    assert out.dispatch_inputs["head_sha"] == "bbb"
    assert out.dispatch_inputs["changed_paths"] == ["app/a.ts"]
    # Versioned, because the far side is a separate deployable.
    assert out.dispatch_inputs["contract_version"] >= 1


@pytest.mark.asyncio
async def test_a_pull_request_is_optional():
    """A nightly regression against a branch has no pull request, and a
    contract that demanded one would forbid a legitimate run."""
    out = await DispatchedQAAgent("github-actions").execute(
        QARequest(run_id="r1", head_sha="bbb")
    )
    assert out.dispatch_inputs["change_request_id"] == ""


# ── what a provider owes back ─────────────────────────────────────────────


def test_a_result_carries_evidence_not_just_a_verdict():
    """A provider that returns "passed" and nothing else has reported an
    opinion, and the release gate treats it as one."""
    proven = DispatchedQAAgent("x").read_result(
        {
            "passed": True,
            "evidence_ref": "https://ci/run/9",
            "assertions": [{"edge": "COVERS", "src": {}, "dst": {}}],
            "covered_criteria": ["ac-1"],
            "uncovered_criteria": ["ac-2"],
        }
    )
    assert proven.passed is True
    assert proven.evidence_ref.endswith("/9")
    assert len(proven.assertions) == 1
    assert proven.covered_criteria == ["ac-1"]
    assert proven.uncovered_criteria == ["ac-2"]


def test_a_silent_provider_is_not_read_as_a_pass():
    """Tolerant of a provider answering less than the full contract — the
    one thing it will not do is invent a pass."""
    proven = DispatchedQAAgent("x").read_result({})
    assert proven.passed is False
    assert proven.assertions == []
    assert proven.covered_criteria == []


def test_missing_coverage_is_reported_as_missing_not_inferred():
    proven = DispatchedQAAgent("x").read_result({"passed": True})
    assert proven.passed is True
    # Not "everything", which is what inferring would give.
    assert proven.covered_criteria == []


# ── local keeps the work inside the boundary ──────────────────────────────


def test_the_local_provider_declares_where_it_runs():
    """The distinction that matters to a client with a residency question."""
    assert LocalQAAgent().capabilities()["runs_in_platform_boundary"] is True
    assert "runs_in_platform_boundary" not in DispatchedQAAgent("github-actions").capabilities()


@pytest.mark.asyncio
async def test_both_shapes_park_rather_than_blocking():
    """"Inside the boundary" is about where the work happens and who sees the
    source, not about whether the phase waits synchronously. A QA run takes
    minutes; a coroutine blocked on it loses the run on a restart."""
    for agent in (LocalQAAgent(), DispatchedQAAgent("github-actions")):
        out = await agent.execute(QARequest(run_id="r1", head_sha="bbb", branch="b"))
        assert out.state == "pending"
        assert agent.capabilities()["dispatched"] is True


@pytest.mark.asyncio
async def test_the_local_pipeline_says_what_it_needs_before_a_subprocess_fails():
    out = await LocalQAAgent().execute(QARequest(run_id="r1"))
    assert out.state == "failed"
    assert "branch" in out.detail


# ── capabilities change what the gate can conclude ────────────────────────


def test_a_provider_that_cannot_report_coverage_is_known_in_advance():
    class Opaque(DispatchedQAAgent):
        def capabilities(self):
            return {**super().capabilities(), "reports_coverage": False}

    assert Opaque("legacy").capabilities()["reports_coverage"] is False
    # The phase records that the coverage half of the gate was not
    # evaluated, rather than reading silence as full coverage.
