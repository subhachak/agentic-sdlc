"""The harness itself, exercised without a model.

An eval suite nobody can trust is worse than none, so the scoring is tested
the same way everything else is: with doubles, deterministically.
"""

from __future__ import annotations

import pytest

from evals.runner import Case, load_cases, report, run_case
from evals.scoring import CaseResult, Outcome, check_expectations, jaccard, stability
from tests.graph_doubles import InMemoryContextGraph
from tests.implementation_doubles import StubSourceControl


# --- scoring ---------------------------------------------------------------


def test_identical_runs_are_perfectly_stable():
    runs = [Outcome(True, files=["a"]), Outcome(True, files=["a"])]
    assert stability(runs) == 1.0


def test_disjoint_runs_are_maximally_unstable():
    runs = [Outcome(True, files=["a"]), Outcome(True, files=["b"])]
    assert stability(runs) == 0.0


def test_stability_ignores_runs_that_produced_nothing():
    """A blocked run has no file set to agree or disagree with, and counting it
    as disagreement would punish a phase for declining correctly."""
    runs = [Outcome(True, files=["a"]), Outcome(False, blocked="cannot"), Outcome(True, files=["a"])]
    assert stability(runs) == 1.0


def test_a_single_usable_run_is_not_called_stable_on_no_evidence():
    assert stability([Outcome(False, error="boom")]) == 0.0


def test_jaccard_of_two_empty_sets_is_agreement():
    assert jaccard(set(), set()) == 1.0


# --- expectations ----------------------------------------------------------


def test_a_run_meeting_every_expectation_has_no_failures():
    outcome = Outcome(True, files=["app/claims/page.tsx"], modules=["app/claims"])
    assert check_expectations(outcome, {
        "accepted": True, "blocked": False,
        "must_touch": ["claims/page.tsx"], "must_not_touch": [".github/"], "max_files": 2,
    }) == []


def test_a_missing_required_file_is_a_failure():
    failures = check_expectations(Outcome(True, files=["other.ts"]), {"must_touch": ["page.tsx"]})
    assert failures and "page.tsx" in failures[0]


def test_touching_a_forbidden_path_is_a_failure():
    failures = check_expectations(
        Outcome(True, files=[".github/workflows/x.yml"]), {"must_not_touch": [".github/"]}
    )
    assert failures and "must_not_touch" in failures[0]


def test_declining_when_a_change_was_expected_is_a_failure():
    failures = check_expectations(Outcome(False, blocked="no mail capability"), {"blocked": False})
    assert failures and "declined" in failures[0]


def test_proposing_when_a_decline_was_expected_is_a_failure():
    """The case that matters most: a confident design for a capability the
    codebase does not have is worse than no design."""
    failures = check_expectations(Outcome(True, files=["a.ts"]), {"blocked": True})
    assert failures and "expected the agent to decline" in failures[0]


def test_sprawl_is_a_failure():
    failures = check_expectations(Outcome(True, files=list("abcde")), {"max_files": 3})
    assert failures and "at most 3" in failures[0]


# --- aggregation -----------------------------------------------------------


def test_rates_are_computed_over_repeats():
    runs = [Outcome(True, files=["a"]), Outcome(False, error="x"), Outcome(True, files=["a"])]
    result = CaseResult("c", "design", runs, [[], ["boom"], []])

    assert result.repeats == 3
    assert round(result.accept_rate, 2) == 0.67
    assert round(result.expectation_rate, 2) == 0.67


def test_the_report_names_the_failures_it_counted():
    result = CaseResult("c", "design", [Outcome(True)], [["must_touch: nothing matching 'x'"]])
    text = report([result])
    assert "c" in text and "must_touch" in text


# --- cases and the runner --------------------------------------------------


def test_the_shipped_cases_load_and_declare_expectations():
    cases = load_cases()
    assert cases
    for case in cases:
        assert case.phase in ("design", "implementation")
        assert case.requirement.strip()
        assert case.expects, f"{case.name} asserts nothing"


def test_at_least_one_case_expects_the_agent_to_decline():
    assert any(c.expects.get("blocked") is True for c in load_cases())


class _FlakyLLM:
    """Names a different module every other call."""

    def __init__(self):
        self.calls = 0

    async def complete_json(self, system, user, schema, *, max_tokens=16000):
        self.calls += 1
        path = "demo-app/app/claims/page.tsx" if self.calls % 2 else "demo-app/app/api/route.ts"
        return schema(summary="s", rationale="r", modules=["demo-app/app/claims"],
                      files=[path], criteria_addressed=[])


@pytest.mark.asyncio
async def test_an_unstable_phase_is_reported_as_unstable():
    """The property nothing else in the suite can see: every answer admissible,
    and a different one each time."""
    case = Case(name="c", phase="design", requirement="do a thing", expects={})
    result = await run_case(
        case, llm=_FlakyLLM(), graph=InMemoryContextGraph(),
        source_control=StubSourceControl(), repeats=4,
    )

    assert result.repeats == 4
    assert result.file_stability < 1.0


@pytest.mark.asyncio
async def test_a_provider_failure_is_recorded_not_raised():
    class _Broken:
        async def complete_json(self, *a, **k):
            raise RuntimeError("rate limited")

    case = Case(name="c", phase="design", requirement="x", expects={"accepted": True})
    result = await run_case(case, llm=_Broken(), graph=InMemoryContextGraph(), repeats=2)

    assert result.accept_rate == 0.0
    assert all("rate limited" in r.error for r in result.runs)


def test_a_case_expecting_a_decline_does_not_drag_down_the_accept_rate():
    """Refusing is the correct answer there. Averaging it in reports a worse
    system than the one being measured."""
    declining = CaseResult("no-capability", "design",
                           [Outcome(False, blocked="no mail")], [[]], expects_decline=True)
    producing = CaseResult("normal", "design", [Outcome(True, files=["a"])], [[]])

    text = report([declining, producing])

    assert "100%" in text
    assert "what the case expects" in text
    assert declining.decline_rate == 1.0
