"""Seeding: the plan declares what it needs, this node guarantees it.

The regression these cover is specific. The seeder used to guess from
scenario prose against three hardcoded status strings; the first run against
a real planner proposed a scenario about a fourth status, nothing was seeded,
and the failure surfaced three phases later as a browser test complaining
about missing data.
"""

from __future__ import annotations

import json

import pytest

from orchestrator import data_store
from orchestrator.nodes import test_data


@pytest.fixture
def store(tmp_path, monkeypatch):
    path = tmp_path / "data-store.json"
    path.write_text(json.dumps({
        "claims": [
            {"id": "CLM-1001", "policyholder": "J. Alvarez", "status": "Under Review",
             "lastUpdated": "2026-08-10"},
            {"id": "CLM-1002", "policyholder": "M. Chen", "status": "Approved",
             "lastUpdated": "2026-08-14"},
        ]
    }))
    monkeypatch.setattr(data_store, "DATA_STORE", path)
    return path


def _scenario(*requirements):
    return {"id": "s1", "required_data": list(requirements)}


def _need(value, field="status", entity="claims", count=1):
    return {"entity": entity, "field": field, "value": value, "count": count}


# --- shape -----------------------------------------------------------------


def test_shape_is_derived_from_the_data_not_declared(store):
    assert data_store.shape() == {
        "claims": {"id", "policyholder", "status", "lastUpdated"}
    }


def test_ids_continue_the_existing_scheme(store):
    rows = data_store.load()["claims"]
    assert data_store.next_id(rows, "claims") == "CLM-1003"


def test_a_fixture_is_shaped_like_the_rows_already_there(store):
    rows = data_store.load()["claims"]
    row = data_store.make_row(rows, "claims", "status", "Escalated")

    assert set(row) == set(rows[0])
    assert row["status"] == "Escalated"


# --- seeding ---------------------------------------------------------------


def test_a_value_the_store_has_never_held_is_created(store):
    """The exact case the first real run failed on: a planner proposing a
    status outside the three the seeder used to know about."""
    result = test_data.run({"test_plan": [_scenario(_need("Escalated"))]})

    statuses = [c["status"] for c in json.loads(store.read_text())["claims"]]
    assert "Escalated" in statuses
    assert result["seed_unsatisfiable"] == []
    assert "Escalated" in result["seed_summary"]


def test_a_value_already_present_is_not_duplicated(store):
    test_data.run({"test_plan": [_scenario(_need("Approved"))]})

    claims = json.loads(store.read_text())["claims"]
    assert sum(1 for c in claims if c["status"] == "Approved") == 1
    assert len(claims) == 2


def test_a_count_greater_than_one_tops_up_to_that_many(store):
    test_data.run({"test_plan": [_scenario(_need("Approved", count=3))]})

    claims = json.loads(store.read_text())["claims"]
    assert sum(1 for c in claims if c["status"] == "Approved") == 3


def test_seeding_twice_changes_nothing_the_second_time(store):
    plan = {"test_plan": [_scenario(_need("Denied"))]}
    test_data.run(plan)
    before = store.read_text()
    test_data.run(plan)

    assert store.read_text() == before


def test_requirements_across_scenarios_are_all_satisfied(store):
    test_data.run({"test_plan": [
        {"id": "a", "required_data": [_need("Escalated")]},
        {"id": "b", "required_data": [_need("Withdrawn")]},
    ]})

    statuses = {c["status"] for c in json.loads(store.read_text())["claims"]}
    assert {"Escalated", "Withdrawn"} <= statuses


# --- what it cannot do, said out loud --------------------------------------


def test_an_unknown_entity_is_reported_not_silently_skipped(store):
    result = test_data.run({"test_plan": [_scenario(_need("x", entity="policies"))]})

    assert result["seed_unsatisfiable"] == ["s1: no policies.status in the data store"]
    assert "Could not satisfy" in result["seed_summary"]


def test_an_unknown_field_is_reported(store):
    result = test_data.run({"test_plan": [_scenario(_need("x", field="premium"))]})

    assert "claims.premium" in result["seed_unsatisfiable"][0]


def test_an_unsatisfiable_requirement_does_not_block_the_others(store):
    result = test_data.run({"test_plan": [
        {"id": "a", "required_data": [_need("x", entity="policies")]},
        {"id": "b", "required_data": [_need("Escalated")]},
    ]})

    statuses = {c["status"] for c in json.loads(store.read_text())["claims"]}
    assert "Escalated" in statuses
    assert len(result["seed_unsatisfiable"]) == 1


def test_a_plan_declaring_nothing_seeds_nothing(store):
    before = store.read_text()
    result = test_data.run({"test_plan": [{"id": "s1"}]})

    assert store.read_text() == before
    assert "already satisfied" in result["seed_summary"]
