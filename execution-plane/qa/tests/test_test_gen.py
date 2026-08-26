"""Script selection decides whether the library is reused or a new spec is
generated. Matching too loosely collapses every scenario onto one script;
matching too tightly regenerates work the library already covers.
"""
from __future__ import annotations

from orchestrator.nodes.test_gen import _select_existing, _spec_filename
from orchestrator.ports import ready


REGRESSION = {
    "id": "claims-table-renders",
    "title": "Claims table still renders every claim",
    "target_route": "/claims",
    "expected_outcome": "One row per claim, each showing id, policyholder, status and last updated",
    "ac_ref": "Table renders one row per claim in the data store",
}

FILTER_SCENARIOS = [
    {
        "id": "filter-approved",
        "title": "Filtering by Approved shows only approved claims",
        "target_route": "/claims",
        "expected_outcome": "Only rows with data-status='Approved' are visible",
        "ac_ref": "Selecting a status shows only rows matching that status",
    },
    {
        "id": "filter-default-all",
        "title": "Status filter defaults to All",
        "target_route": "/claims",
        "expected_outcome": "The status-filter select has value 'All' on first load",
        "ac_ref": "Filter dropdown defaults to All",
    },
    {
        "id": "filter-empty-state",
        "title": "A status with no matching claims shows the empty state",
        "target_route": "/claims",
        "expected_outcome": "The empty-state message is visible and no rows render",
        "ac_ref": "Selecting a status with zero matching claims shows an empty-state message",
    },
]


def test_reuses_the_library_script_for_an_equivalent_scenario(manifest):
    assert _select_existing(REGRESSION, manifest)["id"] == "claims-list-renders"


def test_filter_scenarios_do_not_all_collapse_onto_the_list_script(manifest):
    """Regression: matching did `tag in haystack` as a substring, and the tag
    "claims" is inside the route "/claims". Every scenario matched the first
    manifest entry, so the generation path was unreachable and four
    assignments wrote to one file."""
    assert [_select_existing(s, manifest) for s in FILTER_SCENARIOS] == [None, None, None]


def test_route_mismatch_blocks_an_otherwise_textual_match(manifest):
    api_scenario = {**REGRESSION, "id": "api-claims", "target_route": "/api/claims"}
    assert _select_existing(api_scenario, manifest) is None


def test_tags_are_matched_as_whole_tokens_not_substrings(manifest):
    """The scenario's route is /claims but its text never mentions claims,
    lists or regressions, so no tag applies."""
    unrelated = {
        "id": "nav-link",
        "title": "Home page links to the dashboard",
        "target_route": "/claims",
        "expected_outcome": "The nav-claims link is visible and points at /claims",
        "ac_ref": "Navigation is reachable from the home page",
    }
    assert _select_existing(unrelated, manifest) is None


def test_picks_the_best_scoring_entry_not_the_first(manifest):
    """A partial match listed first must not beat a fuller match listed
    later — this one also checks pagination, which the scenario says
    nothing about."""
    partial = {
        "id": "claims-list-paginated",
        "file": "claims-paginated.spec.ts",
        "route": "/claims",
        "tags": ["claims"],
        "covers": (
            "Claims table renders id, policyholder, status, last updated "
            "and the pagination footer with page numbers"
        ),
    }

    assert _select_existing(REGRESSION, [partial, *manifest])["id"] == "claims-list-renders"


def test_empty_manifest_forces_generation():
    assert _select_existing(REGRESSION, []) is None


def test_spec_filename_is_derived_from_the_scenario_id():
    assert _spec_filename("filter-approved") == "filter-approved.spec.ts"


def test_spec_filename_normalises_and_never_mangles_the_extension():
    """Regression: the old path ran the model's proposed file name through a
    character filter that turned ".spec.ts" into "-spec-ts"."""
    assert _spec_filename("Filter By Status!") == "filter-by-status.spec.ts"
    assert _spec_filename("") == "scenario.spec.ts"


# --- substituting a client's agent -----------------------------------------


def test_a_client_agents_spec_is_sandboxed_like_any_other(tmp_path, monkeypatch):
    """The sandbox was built for agent-authored code and does not care which
    agent. A client's is the one that can change without anyone here
    knowing."""
    import orchestrator.nodes.test_gen as test_gen

    monkeypatch.setattr(test_gen, "GENERATED_DIR", tmp_path)

    class _Hostile:
        def propose_plan(self, request):  # pragma: no cover - generation only
            raise NotImplementedError

        def write_spec(self, request):
            return ready(
                spec="import fs from 'node:fs';\ntest('x', async () => { fs.rmSync('/'); });"
            )

    state = {
        "test_plan": [{"id": "s1", "title": "t", "expected_outcome": "x",
                       "target_route": "/nowhere"}],
        "regression_scope": {"required_scripts": []},
    }
    result = test_gen.run(state, author=_Hostile())

    assert result["test_assignments"] == []
    assert any("Node builtin" in r for r in result["generation_rejections"])
    assert not list(tmp_path.glob("*.spec.ts"))
