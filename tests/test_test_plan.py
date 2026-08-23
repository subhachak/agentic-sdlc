"""The testability gate is the pipeline's claim that an agent cannot wave
its own vague scenario through. These tests pin what it actually rejects.
"""
from __future__ import annotations

import pytest

from orchestrator.nodes.test_plan import _is_testable, run


CONCRETE = "Table shows exactly 2 rows, both with data-status='Approved'"


@pytest.mark.parametrize(
    "outcome",
    [
        CONCRETE,
        "The empty-state message 'No claims match this filter.' is visible",
        "GET /api/claims?status=Denied returns exactly 1 claim",
    ],
)
def test_accepts_concrete_outcomes(outcome):
    ok, reason = _is_testable({"expected_outcome": outcome})
    assert ok is True and reason is None


@pytest.mark.parametrize(
    "outcome",
    ["", "   ", "the filter should work", "it works correctly", "everything looks good"],
)
def test_rejects_vague_or_empty_outcomes(outcome):
    ok, reason = _is_testable({"expected_outcome": outcome})
    assert ok is False and reason


def test_rejects_a_missing_outcome_key():
    ok, reason = _is_testable({"title": "no outcome at all"})
    assert ok is False and reason == "no expected_outcome"


def test_plan_passes_when_every_scenario_is_concrete(monkeypatch):
    monkeypatch.setattr("orchestrator.nodes.test_plan.ask", _Agent([_sc("s1", CONCRETE)]))

    result = run(STATE)

    assert result["test_plan_gate_passed"] is True
    assert [s["id"] for s in result["test_plan"]] == ["s1"]


def test_one_vague_scenario_holds_back_the_whole_plan(monkeypatch):
    """The concrete sibling is not enough — an agent that will not fix s2
    never gets past the gate, however good the rest of the plan is."""
    stubborn = [_sc("s1", CONCRETE), _sc("s2", "the filter should work")]
    monkeypatch.setattr("orchestrator.nodes.test_plan.ask", _Agent(stubborn))

    result = run(STATE)

    assert result["test_plan_gate_passed"] is False
    assert any("s2: rejected" in r for r in result["test_plan_gate_reasons"])


def test_empty_plan_does_not_pass_the_gate(monkeypatch):
    monkeypatch.setattr("orchestrator.nodes.test_plan.ask", _Agent([]))

    result = run(STATE)

    assert result["test_plan_gate_passed"] is False
    assert any("no scenarios at all" in r for r in result["test_plan_gate_reasons"])


# --- revision loop -------------------------------------------------------

class _Agent:
    """Returns a canned plan per attempt, and records what it was told."""

    def __init__(self, *plans):
        self.plans = list(plans)
        self.prompts = []

    def __call__(self, system, user, schema, **kwargs):
        self.prompts.append(user)
        scenarios = self.plans[min(len(self.prompts) - 1, len(self.plans) - 1)]
        return schema(scenarios=scenarios)


def _sc(sid, outcome):
    return {
        "id": sid, "title": sid, "type": "functional", "target_route": "/claims",
        "expected_outcome": outcome, "priority": "P1", "confidence": "high", "ac_ref": "ac",
    }


STATE = {"change_summary": "added filter", "affected_areas": ["/claims"]}


def test_a_vague_plan_is_revised_and_then_accepted(monkeypatch):
    agent = _Agent([_sc("s1", "should work")], [_sc("s1", CONCRETE)])
    monkeypatch.setattr("orchestrator.nodes.test_plan.ask", agent)

    result = run(STATE)

    assert result["test_plan_gate_passed"] is True
    assert result["test_plan_attempts"] == 2
    assert len(agent.prompts) == 2


def test_the_revision_prompt_carries_the_rejection_reasons_back(monkeypatch):
    agent = _Agent([_sc("s1", "should work")], [_sc("s1", CONCRETE)])
    monkeypatch.setattr("orchestrator.nodes.test_plan.ask", agent)

    run(STATE)

    second = agent.prompts[1]
    assert "rejected by the testability gate" in second
    assert "s1: rejected" in second


def test_it_gives_up_after_the_attempt_limit(monkeypatch):
    from orchestrator.nodes.test_plan import MAX_ATTEMPTS

    agent = _Agent([_sc("s1", "should work")])
    monkeypatch.setattr("orchestrator.nodes.test_plan.ask", agent)

    result = run(STATE)

    assert result["test_plan_gate_passed"] is False
    assert result["test_plan_attempts"] == MAX_ATTEMPTS
    assert len(agent.prompts) == MAX_ATTEMPTS
    assert "still not testable after" in result["test_plan_gate_reasons"][0]


def test_a_first_attempt_that_passes_does_not_retry(monkeypatch):
    agent = _Agent([_sc("s1", CONCRETE)])
    monkeypatch.setattr("orchestrator.nodes.test_plan.ask", agent)

    result = run(STATE)

    assert result["test_plan_attempts"] == 1
    assert len(agent.prompts) == 1
    assert "rejected" not in agent.prompts[0]
