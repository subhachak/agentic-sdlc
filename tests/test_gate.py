"""The gate decides pass/fail for the whole PR. If it misreads Playwright's
output it either files defects against a green build or waves a red one
through, and in both cases the PR comment reads as authoritative.
"""
from __future__ import annotations

from orchestrator.nodes.gate import _walk_results, run


def test_finds_tests_nested_under_specs(playwright_report, spec):
    """Regression: the walker used to look for a `tests` key directly on the
    suite. Playwright puts tests under suites[].specs[].tests[], so it found
    nothing and every run reported 0 tests executed."""
    report = playwright_report(spec("claims table renders all claims"))

    leaves = _walk_results(report)

    assert leaves == [{"title": "claims table renders all claims", "status": "expected"}]


def test_takes_title_from_the_spec_not_the_test(playwright_report, spec):
    leaves = _walk_results(playwright_report(spec("filtering by Approved")))
    assert leaves[0]["title"] == "filtering by Approved"


def test_descends_into_nested_describe_blocks(playwright_report, spec):
    report = playwright_report(
        spec("top level"),
        nested=[{"title": "describe block", "specs": [spec("inner")], "suites": []}],
    )
    assert {l["title"] for l in _walk_results(report)} == {"top level", "inner"}


def test_falls_back_to_last_result_when_status_absent(playwright_report):
    report = playwright_report(
        {"title": "legacy shape", "tests": [{"results": [{"status": "passed"}]}]}
    )
    assert _walk_results(report) == [{"title": "legacy shape", "status": "passed"}]


def test_unknown_when_a_test_produced_no_results(playwright_report):
    report = playwright_report({"title": "never ran", "tests": [{"results": []}]})
    assert _walk_results(report)[0]["status"] == "unknown"


def test_empty_report_yields_no_leaves():
    assert _walk_results({"config": {}, "suites": [], "errors": []}) == []


def test_passes_when_every_planned_scenario_ran_and_passed(playwright_report, spec):
    state = {
        "test_plan": [{"id": "a"}, {"id": "b"}],
        "test_assignments": [{"scenario_id": "a"}, {"scenario_id": "b"}],
        "run_results_raw": playwright_report(spec("a"), spec("b")),
    }

    result = run(state)

    assert result["gate_passed"] is True
    assert result["failing_scenarios"] == []


def test_fails_when_a_test_failed(playwright_report, spec):
    state = {
        "test_plan": [{"id": "a"}],
        "test_assignments": [{"scenario_id": "a"}],
        "run_results_raw": playwright_report(spec("a", status="unexpected")),
    }

    result = run(state)

    assert result["gate_passed"] is False
    assert result["failing_scenarios"] == ["a"]


def test_fails_when_a_scenario_never_got_an_assignment(playwright_report, spec):
    state = {
        "test_plan": [{"id": "a"}, {"id": "b"}],
        "test_assignments": [{"scenario_id": "a"}],
        "run_results_raw": playwright_report(spec("a")),
    }

    result = run(state)

    assert result["gate_passed"] is False
    assert "1/2 planned scenarios got a test assignment" in result["gate_reasons"][0]


def test_fails_when_an_assigned_test_never_ran(playwright_report, spec):
    state = {
        "test_plan": [{"id": "a"}, {"id": "b"}],
        "test_assignments": [{"scenario_id": "a"}, {"scenario_id": "b"}],
        "run_results_raw": playwright_report(spec("a")),
    }

    result = run(state)

    assert result["gate_passed"] is False
    assert "1/2 assigned tests actually ran" in result["gate_reasons"][0]


def test_skipped_and_flaky_do_not_count_as_passed(playwright_report, spec):
    state = {
        "test_plan": [{"id": "a"}, {"id": "b"}],
        "test_assignments": [{"scenario_id": "a"}, {"scenario_id": "b"}],
        "run_results_raw": playwright_report(
            spec("skipped one", status="skipped"), spec("flaky one", status="flaky")
        ),
    }

    result = run(state)

    assert result["gate_passed"] is False
    assert set(result["failing_scenarios"]) == {"skipped one", "flaky one"}


def test_missing_results_file_fails_closed():
    state = {
        "test_plan": [{"id": "a"}, {"id": "b"}],
        "run_results_raw": {"error": "no results.json produced"},
    }

    result = run(state)

    assert result["gate_passed"] is False
    assert result["failing_scenarios"] == ["a", "b"]
