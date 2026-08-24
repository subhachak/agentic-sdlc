"""The QA pipeline's half of the context graph: what it reads to widen
regression scope, and what it emits for the control plane to ingest.
"""

from __future__ import annotations

from orchestrator.context import (
    library_script_ids,
    blast_radius,
    build_assertions,
    modules_for_paths,
    criterion_ids,
    regression_candidates,
    scripts_covering,
    graph_provenance,
    graph_warnings,
    api_contract,
    ui_contract,
)
from orchestrator.identity import node_id


# --- reading the code intelligence graph -----------------------------------


def test_criteria_have_stable_ids():
    known = criterion_ids()
    assert "claims-status-filter/ac-2" in known
    assert known["claims-status-filter/ac-2"]["module"] == "claims-filter"


def test_a_changed_file_maps_to_its_component():
    assert modules_for_paths(["demo-app/app/api/claims/route.ts"]) == {"demo-app/app/api/claims"}


def test_blast_radius_includes_dependents_not_just_the_change():
    """The point of the graph: a change to the API can break the table and
    the filter, neither of which the diff touched."""
    assert blast_radius({"demo-app/app/api/claims"}) == {
        "demo-app/app/api/claims",
        "demo-app/app/claims",
    }


def test_regression_scope_widens_beyond_the_diff():
    scope = regression_candidates(["demo-app/app/api/claims/route.ts"])

    assert scope["changed_components"] == ["demo-app/app/api/claims"]
    assert set(scope["impacted_components"]) == {
        "demo-app/app/api/claims",
        "demo-app/app/claims",
    }
    # A script covering a module the diff never touched, required because the
    # API it depends on changed.
    assert scope["required_scripts"] == ["claims-list-renders"]


def test_coverage_is_resolved_against_the_library_not_taken_on_trust():
    """Every `covered_by` entry in the graph used to name a script that did
    not exist — the library holds `claims-list-renders` and the graph claimed
    `claims-table-renders`, `filter-approved` and three more. The whole
    regression set resolved to nothing, and nothing said so."""
    assert scripts_covering({"demo-app/app/claims"}) <= library_script_ids()


def test_a_module_with_no_script_is_reported_as_a_gap_not_as_covered():
    scope = regression_candidates(["demo-app/app/api/claims/route.ts"])

    # The route file itself: the list script exercises it through the page,
    # which is not the same claim as covering it.
    assert "demo-app/app/api/claims" in scope["uncovered_components"]
    assert scope["dangling_coverage"] == []


def test_coverage_recorded_against_a_module_that_no_longer_exists_is_dangling(monkeypatch):
    """The graph is regenerated; the manifest is not. A script still claiming
    a module the export no longer contains has coverage nothing has."""
    import orchestrator.context as context

    monkeypatch.setattr(
        context, "_load_manifest",
        lambda: [{"id": "ghost-script", "covers_modules": ["module/that/went/away"]}],
    )
    scope = context.regression_candidates(["demo-app/app/claims/page.tsx"])

    assert scope["dangling_coverage"] == ["ghost-script -> module/that/went/away"]


# --- provenance ------------------------------------------------------------


def test_the_graph_says_which_commit_it_describes():
    provenance = graph_provenance()

    assert provenance["generated"] is True
    assert len(provenance["commit_sha"]) == 40
    assert provenance["scope"] == "demo-app"


def test_a_graph_describing_another_commit_is_flagged():
    """Not a failure — a stale graph still scopes better than none. Flagged so
    the answer is qualified rather than presented as certain."""
    warnings = graph_warnings(head_sha="f" * 40)

    assert len(warnings) == 1
    assert "not the fffffff under test" in warnings[0]


def test_a_hand_maintained_graph_is_flagged_as_such(monkeypatch):
    import orchestrator.context as context

    monkeypatch.setattr(context, "_load_code_graph", lambda: {"modules": [], "depends_on": []})
    assert "hand-maintained" in context.graph_warnings()[0]


def test_a_graph_matching_the_commit_under_test_warns_about_nothing():
    assert graph_warnings(head_sha=graph_provenance()["commit_sha"]) == []



def test_an_unrelated_change_pulls_in_nothing():
    scope = regression_candidates(["README.md"])
    assert (scope["impacted_components"], scope["required_scripts"]) == ([], [])


def test_scripts_covering_an_unknown_module_is_empty():
    assert scripts_covering({"does-not-exist"}) == set()


# --- emitting assertions ---------------------------------------------------


STATE = {
    "repo": "acme/demo",
    "pr_number": 7,
    "gate_passed": True,
    "test_plan": [
        {"id": "filter-denied", "title": "Filtering by Denied", "type": "functional",
         "ac_ref": "claims-status-filter/ac-2"},
        {"id": "orphan", "title": "No criterion", "type": "functional", "ac_ref": "nope/ac-1"},
    ],
    "test_assignments": [
        {"scenario_id": "filter-denied", "mode": "generated", "file_path": "/x/filter-denied.spec.ts"},
        {"scenario_id": "orphan", "mode": "generated", "file_path": "/x/orphan.spec.ts"},
    ],
    "evidence_summary": {"html_report": "evidence/html-report/index.html",
                         "screenshot_count": 2, "trace_count": 2},
    "failing_scenarios": [],
}


def _edges(assertions, edge_type):
    return [a for a in assertions if a["edge"] == edge_type]


def test_a_resolvable_reference_becomes_a_verified_by_edge():
    verified = _edges(build_assertions(STATE), "VERIFIED_BY")

    assert len(verified) == 1
    assert verified[0]["src"]["external_id"] == "claims-status-filter/ac-2"
    assert verified[0]["dst"]["external_id"] == "filter-denied"


def test_an_unresolvable_reference_asserts_nothing():
    """The gate should have rejected it upstream, but the graph must not
    invent a criterion node for a reference that resolves to nothing."""
    ids = [a["src"]["external_id"] for a in _edges(build_assertions(STATE), "VERIFIED_BY")]
    assert "nope/ac-1" not in ids


def test_the_chain_from_scenario_to_run_is_complete():
    assertions = build_assertions(STATE)

    assert len(_edges(assertions, "IMPLEMENTED_BY")) == 2
    assert len(_edges(assertions, "EXERCISED_IN")) == 2
    assert len(_edges(assertions, "PRODUCED")) == 1


def test_a_passing_run_is_marked_passed():
    run = _edges(build_assertions(STATE), "EXERCISED_IN")[0]["dst"]
    assert run["projection"]["status"] == "passed"


def test_failures_become_defect_edges():
    state = {**STATE, "gate_passed": False, "failing_scenarios": ["filter by Denied"]}
    raised = _edges(build_assertions(state), "RAISED")

    assert len(raised) == 1
    assert raised[0]["dst"]["external_id"] == "filter by Denied"
    assert raised[0]["src"]["projection"]["status"] == "failed"


def test_component_dependencies_travel_with_the_result():
    depends = _edges(build_assertions(STATE), "DEPENDS_ON")
    pairs = {(a["src"]["external_id"], a["dst"]["external_id"]) for a in depends}
    assert ("demo-app/app/claims", "demo-app/app/api/claims") in pairs


def test_node_ids_are_derived_not_allocated():
    """Two runs describing the same criterion must produce the same node id,
    or every cross-run query silently splits."""
    first = build_assertions(STATE)[0]["src"]["id"]
    second = build_assertions(STATE)[0]["src"]["id"]

    assert first == second == node_id(
        "ACCEPTANCE_CRITERION", "features", "claims-status-filter/ac-2"
    )


def test_an_empty_plan_asserts_only_the_static_dependency_edges():
    assertions = build_assertions({**STATE, "test_plan": [], "test_assignments": []})
    assert {a["edge"] for a in assertions} == {"PRODUCED", "DEPENDS_ON"}


# --- the UI contract handed to the generator -------------------------------


def test_the_contract_groups_selectors_by_route():
    """A flat list is what made the generator look for the home page nav link
    on /claims in the first real run."""
    contract = ui_contract()
    home, claims = contract.index("/\n"), contract.index("/claims")

    assert home < claims
    assert contract.index("nav-claims") < claims
    assert contract.index("status-filter") > claims


def test_the_contract_states_the_filter_option_values():
    """The other half of that run's failures: the generator guessed the
    unfiltered option was the empty string, and Playwright spent thirty
    seconds finding out otherwise."""
    contract = ui_contract()
    assert '"All"' in contract
    assert "empty-string" in contract


def test_every_selector_the_app_exposes_is_described():
    contract = ui_contract()
    for testid in ("nav-claims", "claims-table", "claim-row", "status-filter", "empty-state"):
        assert testid in contract


def test_the_api_contract_states_the_response_is_not_an_array():
    """The second real run failed five tests on `Array.isArray(body)` — the
    endpoint returns an object and nothing had ever told the generator so."""
    contract = api_contract()
    assert "never a bare array" in contract
    assert "claims" in contract


def test_the_api_contract_covers_the_filter_parameter():
    contract = api_contract()
    assert "?status=" in contract
    assert "case-insensitive" in contract


# --- path identity ---------------------------------------------------------


def test_a_similar_looking_path_does_not_pull_a_module_into_scope():
    """The old lookup asked whether a graph path appeared anywhere inside a
    changed path, so `demo-app/app/claims/page.tsx` was matched by anything
    containing it — and a module could be scoped in by a file that merely
    shares a prefix."""
    assert modules_for_paths(["vendor/demo-app/app/claims/page.tsx"]) == set()
    assert modules_for_paths(["demo-app/app/claims/page.tsx.bak"]) == set()


def test_paths_match_regardless_of_leading_slash_or_dot():
    assert modules_for_paths(["./demo-app/app/api/claims/route.ts"]) == {
        "demo-app/app/api/claims"
    }
    assert modules_for_paths(["/demo-app/app/api/claims/route.ts"]) == {
        "demo-app/app/api/claims"
    }
