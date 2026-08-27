"""A regression is something this change broke.

The gate failed on any failing required script, which is a test for failures
rather than for regressions. Pointed at a real application that stopped being
a distinction without a difference immediately: Fronei's own e2e suite has
been failing three of five specs in its own CI since July, so every run would
have been refused for something no change under test could fix — and the only
way to ship would have been to turn the gate off.

The same reasoning already governs coverage gaps, which report rather than
block because refusing every such change would refuse every change to a
codebase still building its suite. It had been applied to coverage and not to
regressions.
"""

from __future__ import annotations

from orchestrator.baseline import compare
from orchestrator.nodes import gate


REQUIRED = ["admin-overview", "agent-workbench"]


def test_a_script_already_failing_does_not_block():
    out = compare(["admin-overview"], REQUIRED, {"admin-overview": "failed"})
    assert out.pre_existing == ["admin-overview"]
    assert out.blocking == []


def test_a_script_this_change_broke_does_block():
    out = compare(["admin-overview"], REQUIRED, {"admin-overview": "passed"})
    assert out.regressions == ["admin-overview"]
    assert out.blocking == ["admin-overview"]


def test_the_two_are_distinguished_in_one_run():
    out = compare(
        ["admin-overview", "agent-workbench"],
        REQUIRED,
        {"admin-overview": "failed", "agent-workbench": "passed"},
    )
    assert out.pre_existing == ["admin-overview"]
    assert out.regressions == ["agent-workbench"]
    assert out.blocking == ["agent-workbench"]


def test_a_repair_is_reported_even_though_nothing_turns_on_it():
    """A change that fixes a long-broken regression should be able to say so,
    and it is how a manifest's notion of what passes gets corrected."""
    out = compare([], REQUIRED, {"admin-overview": "failed"})
    assert out.repaired == ["admin-overview"]
    assert out.blocking == []


# ── the failure this must not become ──────────────────────────────────────


def test_no_baseline_is_not_a_blanket_excuse():
    """"Nobody looked" is not "nothing was already broken". Treating an
    unrun baseline as evidence of pre-existing failure would let any run
    that skips the base pass everything, which is a gate that disables
    itself under exactly the conditions it is needed."""
    out = compare(["admin-overview"], REQUIRED, None)
    assert out.established is False
    assert out.pre_existing == []
    assert out.blocking == ["admin-overview"]


def test_a_script_the_baseline_never_reached_still_blocks():
    """Otherwise a script that fails to run at base grants itself an
    exemption at head — the cheapest possible way to defeat the gate."""
    out = compare(["admin-overview"], REQUIRED, {"admin-overview": "missing"})
    assert out.unexplained == ["admin-overview"]
    assert out.blocking == ["admin-overview"]


def test_a_script_absent_from_the_baseline_entirely_still_blocks():
    out = compare(["admin-overview"], REQUIRED, {"agent-workbench": "passed"})
    assert out.blocking == ["admin-overview"]


# ── and it reaches the verdict ────────────────────────────────────────────


def _state(**over):
    base = {
        "run_results_raw": {
            "suites": [
                {
                    "title": "admin.spec.ts",
                    "specs": [
                        {
                            "title": "loads",
                            "file": "admin.spec.ts",
                            "tests": [{"results": [{"status": "unexpected"}], "status": "unexpected"}],
                        }
                    ],
                }
            ]
        },
        "test_plan": [],
        "test_assignments": [
            {
                "scenario_id": "regression:admin-overview",
                "source_script_id": "admin-overview",
                "file_path": "/x/admin.spec.ts",
                "mode": "required-regression",
            }
        ],
        "regression_scope": {"required_scripts": ["admin-overview"]},
        "observed_coverage": {},
    }
    return {**base, **over}


def test_a_pre_existing_failure_lets_the_gate_pass_and_says_why():
    out = gate.run(_state(baseline_verdicts={"admin-overview": "failed"}))

    assert out["gate_passed"] is True
    assert out["regression_differential"]["pre_existing"] == ["admin-overview"]
    assert any("already failing before this change" in n for n in out["gate_reasons"])


def test_an_excused_failure_does_not_return_through_the_general_check():
    """It did. The differential excused it, the note said "not blocking it",
    and the gate failed anyway on the same result — a verdict contradicting
    its own explanation, which is worse than either answer alone."""
    out = gate.run(_state(baseline_verdicts={"admin-overview": "failed"}))
    assert out["failing_scenarios"] == []
    assert not any("test(s) failed" in n for n in out["gate_reasons"])


def test_an_excused_regression_raises_no_defect_against_this_change():
    """failing_scenarios is what the report phase opens defects from. A
    pre-existing failure is real and worth knowing about, but attributing it
    to the change that happened to run next is how a defect tracker fills
    with the same issue once per merge."""
    out = gate.run(_state(baseline_verdicts={"admin-overview": "failed"}))
    assert out["failing_scenarios"] == []
    assert out["regression_differential"]["pre_existing"] == ["admin-overview"]


def test_a_real_regression_still_fails_the_gate():
    out = gate.run(_state(baseline_verdicts={"admin-overview": "passed"}))
    assert out["gate_passed"] is False
    assert out["regression_differential"]["regressions"] == ["admin-overview"]


def test_without_a_baseline_the_run_fails_and_names_the_setting():
    out = gate.run(_state(baseline_verdicts=None))
    assert out["gate_passed"] is False
    assert any("QA_BASE_APP_ROOT" in n for n in out["gate_reasons"])
