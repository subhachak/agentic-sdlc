"""The blast radius as a control rather than a suggestion.

Impacted modules and the scripts covering them used to be interpolated into
the test-planning prompt — "worth reusing as regression" — and nothing
checked the result. An agent could omit every regression candidate and the
plan gate would still pass, because it only asked whether the scenarios the
agent *did* propose were testable. These tests pin the chain that replaced
that: required scripts are installed by code, and the gate refuses a run in
which any of them did not run or did not pass.
"""

from __future__ import annotations

import json

import pytest

from orchestrator.nodes.gate import run as gate
from orchestrator.nodes.test_gen import _install_required_regressions


MANIFEST = [
    {"id": "claims-list-renders", "file": "claims-list.spec.ts", "route": "/claims",
     "tags": ["claims", "list"], "covers": "claims table renders"},
]


# --- installation ----------------------------------------------------------


def test_a_required_script_is_installed_without_the_agent_being_asked(tmp_path, monkeypatch):
    import orchestrator.nodes.test_gen as test_gen

    monkeypatch.setattr(test_gen, "GENERATED_DIR", tmp_path / "generated")
    (tmp_path / "generated").mkdir()
    library = tmp_path / "library"
    library.mkdir()
    (library / "claims-list.spec.ts").write_text("test('x', async () => {});\n")
    monkeypatch.setattr(test_gen, "LIBRARY_DIR", library)

    added, missing = test_gen._install_required_regressions(
        ["claims-list-renders"], MANIFEST, assignments=[]
    )

    assert missing == []
    assert [a["mode"] for a in added] == ["required-regression"]
    assert added[0]["source_script_id"] == "claims-list-renders"
    assert (tmp_path / "generated" / "regression-claims-list-renders.spec.ts").exists()


def test_a_script_already_selected_for_a_scenario_is_not_installed_twice(tmp_path, monkeypatch):
    """Same file, same assertions — running it twice proves nothing and costs
    a browser."""
    import orchestrator.nodes.test_gen as test_gen

    monkeypatch.setattr(test_gen, "GENERATED_DIR", tmp_path)
    monkeypatch.setattr(test_gen, "LIBRARY_DIR", tmp_path)

    added, missing = test_gen._install_required_regressions(
        ["claims-list-renders"],
        MANIFEST,
        assignments=[{"scenario_id": "s1", "source_script_id": "claims-list-renders"}],
    )

    assert (added, missing) == ([], [])


def test_a_required_script_missing_from_the_library_is_reported(tmp_path, monkeypatch):
    import orchestrator.nodes.test_gen as test_gen

    monkeypatch.setattr(test_gen, "GENERATED_DIR", tmp_path)
    added, missing = test_gen._install_required_regressions(["ghost"], MANIFEST, [])

    assert (added, missing) == ([], ["ghost"])


# --- the gate --------------------------------------------------------------


def _report(*specs: dict) -> dict:
    return {"config": {}, "errors": [], "suites": [
        {"title": s["file"], "file": s["file"],
         "specs": [{"title": s.get("title", "t"), "file": s["file"],
                    "tests": [{"status": s.get("status", "expected")}]}],
         "suites": []}
        for s in specs
    ]}


def _state(**overrides) -> dict:
    base = {
        "test_plan": [{"id": "s1"}],
        "test_assignments": [
            {"scenario_id": "s1", "mode": "generated", "file_path": "/g/s1.spec.ts",
             "source_script_id": None},
            {"scenario_id": "regression:claims-list-renders", "mode": "required-regression",
             "file_path": "/g/regression-claims-list-renders.spec.ts",
             "source_script_id": "claims-list-renders"},
        ],
        "regression_scope": {
            "required_scripts": ["claims-list-renders"],
            "uncovered_components": [],
            "dangling_coverage": [],
        },
        "run_results_raw": _report(
            {"file": "s1.spec.ts"},
            {"file": "regression-claims-list-renders.spec.ts"},
        ),
    }
    return {**base, **overrides}


def test_a_run_with_its_required_regression_passing_is_admitted():
    result = gate(_state())

    assert result["gate_passed"] is True
    assert result["required_regressions"] == ["claims-list-renders"]
    assert result["required_regressions_failed"] == []


def test_a_failing_required_regression_fails_the_gate():
    state = _state(run_results_raw=_report(
        {"file": "s1.spec.ts"},
        {"file": "regression-claims-list-renders.spec.ts", "status": "unexpected"},
    ))

    result = gate(state)

    assert result["gate_passed"] is False
    assert result["required_regressions_failed"] == ["claims-list-renders"]
    assert any("required regression scripts failed" in r for r in result["gate_reasons"])


def test_a_required_regression_that_never_ran_fails_the_gate():
    """The precise failure the old count check could not see: the assignment
    existed, so the counts balanced, but the spec produced no result."""
    state = _state(run_results_raw=_report({"file": "s1.spec.ts"}))

    result = gate(state)

    assert result["gate_passed"] is False
    assert result["required_regressions_missing"] == ["claims-list-renders"]


def test_a_required_script_with_no_assignment_at_all_fails_the_gate():
    """The omission case. Nothing installed it, nothing ran it, and every
    count still balances — which is exactly how it passed before."""
    state = _state(
        test_assignments=[
            {"scenario_id": "s1", "mode": "generated", "file_path": "/g/s1.spec.ts",
             "source_script_id": None},
        ],
        run_results_raw=_report({"file": "s1.spec.ts"}),
    )

    result = gate(state)

    assert result["gate_passed"] is False
    assert result["required_regressions_missing"] == ["claims-list-renders"]


def test_dangling_coverage_fails_the_gate():
    """A clean sweep over a regression set that resolved to nothing is worse
    than a failure, because it reads as evidence."""
    state = _state(regression_scope={
        "required_scripts": [],
        "uncovered_components": ["claims-api"],
        "dangling_coverage": ["claims-api -> does-not-exist"],
    })

    result = gate(state)

    assert result["gate_passed"] is False
    assert any("do not exist" in r for r in result["gate_reasons"])


def test_required_regressions_do_not_count_against_the_planned_total():
    """They are not planned scenarios. Comparing assignments to plan length
    without excluding them would report a shortfall that does not exist —
    or hide one that does."""
    result = gate(_state())

    assert not any("planned scenarios got a test assignment" in r
                   for r in result["gate_reasons"])


# --- coverage gaps ---------------------------------------------------------


def test_an_uncovered_impacted_module_is_reported_but_does_not_block(monkeypatch):
    monkeypatch.delenv("QA_REQUIRE_FULL_COVERAGE", raising=False)
    state = _state(regression_scope={
        "required_scripts": ["claims-list-renders"],
        "uncovered_components": ["claims-filter"],
        "dangling_coverage": [],
    })

    result = gate(state)

    assert result["gate_passed"] is True
    assert result["coverage_gaps"] == ["claims-filter"]
    assert any("claims-filter" in r for r in result["gate_reasons"])


def test_coverage_gaps_can_be_made_blocking(monkeypatch):
    """The ratchet a team turns on once its library has caught up."""
    monkeypatch.setenv("QA_REQUIRE_FULL_COVERAGE", "1")
    state = _state(regression_scope={
        "required_scripts": ["claims-list-renders"],
        "uncovered_components": ["claims-filter"],
        "dangling_coverage": [],
    })

    result = gate(state)

    assert result["gate_passed"] is False
    assert any("no regression script" in r for r in result["gate_reasons"])


def test_a_change_that_impacts_nothing_requires_nothing():
    state = _state(
        test_assignments=[{"scenario_id": "s1", "mode": "generated",
                           "file_path": "/g/s1.spec.ts", "source_script_id": None}],
        regression_scope={"required_scripts": [], "uncovered_components": [],
                          "dangling_coverage": []},
        run_results_raw=_report({"file": "s1.spec.ts"}),
    )

    result = gate(state)

    assert result["gate_passed"] is True
    assert result["required_regressions"] == []


# --- what the PR is told ---------------------------------------------------


def test_the_pr_comment_states_which_impacted_modules_nothing_covers():
    """A green tick over an impacted module that no script exercises is the
    thing a reviewer most needs told, and the thing a pass report most easily
    hides."""
    from orchestrator.nodes.report import _blast_radius_block

    block = _blast_radius_block({
        "regression_scope": {"impacted_components": ["claims-api", "claims-filter"]},
        "required_regressions": ["claims-list-renders"],
        "coverage_gaps": ["claims-filter"],
    })

    assert "claims-list-renders" in block
    assert "No regression coverage: claims-filter" in block


def test_a_failed_required_regression_is_named_in_the_comment():
    from orchestrator.nodes.report import _blast_radius_block

    block = _blast_radius_block({
        "regression_scope": {"impacted_components": ["claims-table"]},
        "required_regressions": ["claims-list-renders"],
        "required_regressions_failed": ["claims-list-renders"],
    })

    assert "(failed)" in block
    assert "Failed: claims-list-renders" in block


# --- what the control plane is told ----------------------------------------


def test_an_enforced_regression_produces_a_covers_edge_from_an_actual_run():
    """The stronger kind of coverage claim. `covered_by` in the graph asserts
    that a script covers a module; this records that it did, in this run. A
    hand-written mapping and a runtime observation should not look alike to
    whatever consumes them."""
    from orchestrator.context import build_assertions

    assertions = build_assertions({
        "repo": "acme/thing",
        "pr_number": 7,
        "gate_passed": True,
        "test_plan": [],
        "regression_scope": {"impacted_components": ["demo-app/app/claims"]},
        "test_assignments": [{
            "scenario_id": "regression:claims-list-renders",
            "mode": "required-regression",
            "file_path": "/g/regression-claims-list-renders.spec.ts",
            "source_script_id": "claims-list-renders",
        }],
        # What the run saw this script exercise. Preferred over the manifest,
        # so the edge records evidence rather than restating an intention.
        "observed_coverage": {
            "regression-claims-list-renders.spec.ts": {
                "modules": ["demo-app/app/claims", "demo-app/app"],
                "passed": True,
            }
        },
    })

    covers = [a for a in assertions if a["edge"] == "COVERS"]
    assert [a["dst"]["external_id"] for a in covers] == ["demo-app/app/claims"]
    assert covers[0]["attributes"]["provenance"] == "runtime-observed"
    assert covers[0]["src"]["projection"]["required_by_blast_radius"] is True


def test_a_covers_edge_falls_back_to_the_manifest_when_nothing_was_observed():
    """A run with no usable trace still records what the library claims — and
    says which it is, so a consumer can tell evidence from intent."""
    from orchestrator.context import build_assertions

    assertions = build_assertions({
        "repo": "acme/thing", "pr_number": 7, "gate_passed": True, "test_plan": [],
        "regression_scope": {"impacted_components": ["demo-app/app/api/claims"]},
        "test_assignments": [{
            "scenario_id": "regression:claims-api-contract",
            "mode": "required-regression",
            "file_path": "/g/regression-claims-api-contract.spec.ts",
            "source_script_id": "claims-api-contract",
        }],
    })

    covers = [a for a in assertions if a["edge"] == "COVERS"]
    assert [a["attributes"]["provenance"] for a in covers] == ["declared"]

    kinds = {a["edge"] for a in assertions}
    assert {"IMPLEMENTED_BY", "EXERCISED_IN"} <= kinds


def test_a_regression_covering_an_unimpacted_module_asserts_nothing_about_it():
    """It ran, but not because that module was in the blast radius — so this
    run is not evidence about it."""
    from orchestrator.context import build_assertions

    assertions = build_assertions({
        "repo": "acme/thing", "pr_number": 7, "gate_passed": True, "test_plan": [],
        "regression_scope": {"impacted_components": ["demo-app/app/claims"]},
        "test_assignments": [{
            "scenario_id": "regression:claims-api-contract",
            "mode": "required-regression",
            "file_path": "/g/r.spec.ts",
            "source_script_id": "claims-api-contract",
        }],
        "observed_coverage": {
            "r.spec.ts": {"modules": ["demo-app/app/api/claims"], "passed": True}
        },
    })

    assert [a for a in assertions if a["edge"] == "COVERS"] == []


# --- graph provenance ------------------------------------------------------


def test_a_qualified_graph_is_reported_without_failing_the_run():
    """A stale export still scopes better than none. Refusing would make an
    out-of-date graph worse than never having generated one."""
    state = _state(regression_scope={
        "required_scripts": ["claims-list-renders"],
        "uncovered_components": [],
        "dangling_coverage": [],
        "graph_warnings": ["the code graph describes abc1234, not the def5678 under test"],
    })

    result = gate(state)

    assert result["gate_passed"] is True
    assert result["graph_warnings"] == [
        "the code graph describes abc1234, not the def5678 under test"
    ]
    assert any("abc1234" in r for r in result["gate_reasons"])
