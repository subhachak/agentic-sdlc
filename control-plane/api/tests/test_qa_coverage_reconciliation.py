"""The half of the QA handover that does not move.

A client's QA system decides how to test, what to reuse, what to generate,
how to seed. What it does not decide is whether the difference between what
it was obliged to cover and what it covered gets noticed. That comparison is
ordinary code, it runs here, and these tests exist because an obligation
nobody checks is advice — and advice is what a provider returning
passed=True quietly overrules.
"""

from __future__ import annotations

from app.adapters.qa_agent.dispatched import DispatchedQAAgent
from app.core.qa_coverage import reconcile
from app.ports.qa_agent import QARequest

import pytest


# ── the obligation reaches the provider ───────────────────────────────────


@pytest.mark.asyncio
async def test_the_blast_radius_is_handed_down_not_asked_for():
    """A client's QA system generally has no dependency graph. Asking it to
    widen the changed set means asking it to guess, and where it can answer
    it answers a question this run already settled — which is how the design
    gate and the QA plane came to run on two different blast radii."""
    out = await DispatchedQAAgent("github-actions").execute(
        QARequest(
            run_id="r1",
            head_sha="bbb",
            changed_paths=["apps/web/app/lib/format.ts"],
            impact={"affected": ["apps/web/app/lib/format.ts", "apps/web/app/app/page.tsx"]},
            required_coverage=["apps/web/app/lib", "apps/web/app/app"],
        )
    )
    assert out.dispatch_inputs["required_coverage"] == [
        "apps/web/app/lib",
        "apps/web/app/app",
    ]
    # The whole assessment, not a bare list: a provider that disagrees can
    # disagree with a specific hop rather than with a verdict.
    assert out.dispatch_inputs["impact"]["affected"]


@pytest.mark.asyncio
async def test_the_changed_set_stays_distinct_from_the_reach():
    """Collapsing them would scope regression to exactly the edited files."""
    out = await DispatchedQAAgent("local").execute(
        QARequest(
            run_id="r1",
            head_sha="b",
            changed_paths=["a.ts"],
            required_coverage=["mod/a", "mod/b"],
        )
    )
    assert out.dispatch_inputs["changed_paths"] == ["a.ts"]
    assert out.dispatch_inputs["required_coverage"] == ["mod/a", "mod/b"]


# ── the accounting comes back ─────────────────────────────────────────────


def test_a_provider_that_covers_less_cannot_do_it_silently():
    outcome = reconcile(["mod/a", "mod/b", "mod/c"], ["mod/a"])
    assert outcome.unaccounted == ["mod/b", "mod/c"]
    assert not outcome.complete


def test_declining_to_cover_is_an_answer_and_silence_is_not():
    """Both leave a module untested. Only one of them tells anybody."""
    disclosed = reconcile(["mod/a", "mod/b"], ["mod/a"], ["mod/b"])
    silent = reconcile(["mod/a", "mod/b"], ["mod/a"])

    assert disclosed.declared_uncovered == ["mod/b"]
    assert disclosed.unaccounted == []
    assert disclosed.complete

    assert silent.unaccounted == ["mod/b"]
    assert not silent.complete


def test_covering_more_than_obliged_is_recorded_not_penalised():
    """It is also how a manifest's declared coverage gets corrected by
    observation, so it is worth keeping rather than discarding."""
    outcome = reconcile(["mod/a"], ["mod/a", "mod/z"])
    assert outcome.volunteered == ["mod/z"]
    assert outcome.complete


# ── the failure this module exists to prevent ─────────────────────────────


def test_a_provider_that_cannot_report_coverage_is_unevaluated_not_complete():
    """The tempting shortcut is to treat an empty accounting as "covered
    nothing" or as "nothing to check". The first fails every run from a
    provider that is merely quiet, and teams respond by turning the check
    off. The second is the lie: it reports a release as fully covered on the
    strength of a provider that never looked."""
    outcome = reconcile(["mod/a"], [], reports_coverage=False)
    assert outcome.evaluated is False
    assert outcome.complete is False
    assert outcome.unaccounted == []
    assert "does not report coverage" in outcome.detail


def test_an_empty_obligation_is_complete_only_once_it_was_actually_checked():
    assert reconcile([], []).complete
    assert not reconcile([], [], reports_coverage=False).complete


def test_a_pass_does_not_imply_coverage():
    """The two claims are independent, and the gate is shown both. A change
    whose tests all passed while half its blast radius went untouched is the
    exact shape of a green tick nobody should have trusted."""
    outcome = reconcile(["mod/a", "mod/b"], ["mod/a"])
    assert not outcome.complete
    # Nothing here reads or writes a pass/fail — that is the provider's
    # verdict, and this is the other half of the answer.
    assert "passed" not in outcome.as_dict()
