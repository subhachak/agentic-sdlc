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
    monkeypatch.setattr(
        "orchestrator.nodes.test_plan.ask_json",
        lambda *a, **k: {"scenarios": [{"id": "s1", "expected_outcome": CONCRETE}]},
    )
    state = {"change_summary": "added filter", "affected_areas": ["/claims"]}

    result = run(state)

    assert result["test_plan_gate_passed"] is True
    assert [s["id"] for s in result["test_plan"]] == ["s1"]


def test_one_vague_scenario_rejects_the_whole_plan(monkeypatch):
    monkeypatch.setattr(
        "orchestrator.nodes.test_plan.ask_json",
        lambda *a, **k: {
            "scenarios": [
                {"id": "s1", "expected_outcome": CONCRETE},
                {"id": "s2", "expected_outcome": "the filter should work"},
            ]
        },
    )
    state = {"change_summary": "added filter", "affected_areas": ["/claims"]}

    result = run(state)

    assert result["test_plan_gate_passed"] is False
    assert result["test_plan_gate_reasons"][0].startswith("s2: rejected")


def test_empty_plan_does_not_pass_the_gate(monkeypatch):
    monkeypatch.setattr(
        "orchestrator.nodes.test_plan.ask_json", lambda *a, **k: {"scenarios": []}
    )
    state = {"change_summary": "added filter", "affected_areas": ["/claims"]}

    assert run(state)["test_plan_gate_passed"] is False
