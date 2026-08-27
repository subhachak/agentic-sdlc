"""Test data and test execution as ports, and what they now have to say.

Neither existed. Test data was a module reading one JSON file, called
directly from two nodes; execution was `subprocess.run(["npx","playwright"])`
written into a third. Both are good defaults and neither was replaceable, so
a client whose fixtures live in Postgres or whose suite is Cypress had to
fork the pipeline.
"""

from __future__ import annotations

import json

from pathlib import Path

import pytest

from orchestrator.adapters.json_test_data import JsonFileTestData
from orchestrator.adapters.playwright_runner import PlaywrightRunner
from orchestrator.ports_execution import (
    EXECUTION_CONTRACT_VERSION,
    Attestation,
    Lease,
    workers_for,
)


# ── parallelism is derived, not hardcoded ─────────────────────────────────


@pytest.mark.parametrize(
    "isolation,parallel,mutating,expected",
    [
        # The old rule: mutating specs share a store, so one at a time.
        ("run", True, True, 1),
        ("none", True, True, 1),
        # A provider that can lease per scenario earns concurrency, without
        # anyone editing the run node.
        ("scenario", True, True, 0),
        # Nothing mutating: the runner's own default either way.
        ("run", True, False, 0),
        # A runner that cannot parallelise overrides everything.
        ("scenario", False, True, 1),
    ],
)
def test_worker_count_follows_the_two_declarations(isolation, parallel, mutating, expected):
    assert workers_for(isolation, parallel, mutating) == expected


# ── the provider declares what it can actually do ─────────────────────────


def test_the_json_provider_claims_run_isolation_and_no_more():
    """It is one file the application reads, so two scenarios mutating it are
    visible to each other. Claiming scenario isolation would buy parallelism
    by lying."""
    assert JsonFileTestData().isolation == "run"
    assert JsonFileTestData().contract_version == EXECUTION_CONTRACT_VERSION


# ── teardown is attested, not assumed ─────────────────────────────────────


def test_release_verifies_the_store_came_back(tmp_path, monkeypatch):
    from orchestrator import data_store
    from orchestrator.adapters import json_test_data

    store = tmp_path / "data-store.json"
    store.write_text(json.dumps({"claims": [{"id": "c1"}]}))
    monkeypatch.setattr(data_store, "DATA_STORE", store)
    monkeypatch.setattr(json_test_data, "DATA_STORE", store)

    provider = JsonFileTestData()
    lease = provider.acquire(scope="run-1", scenarios=[])

    # a test mutates the store, as a real one would
    store.write_text(json.dumps({"claims": [{"id": "c1"}, {"id": "c2"}]}))

    attestation = provider.release(lease)
    assert attestation.restored is True
    assert attestation.verified is True
    assert attestation.residue == []
    assert json.loads(store.read_text()) == {"claims": [{"id": "c1"}]}


def test_a_store_that_did_not_exist_is_removed_rather_than_emptied(tmp_path, monkeypatch):
    """None and an empty store are different states. Writing an empty file
    where there was no file leaves a git-tracked artefact behind."""
    from orchestrator import data_store
    from orchestrator.adapters import json_test_data

    store = tmp_path / "data-store.json"
    monkeypatch.setattr(data_store, "DATA_STORE", store)
    monkeypatch.setattr(json_test_data, "DATA_STORE", store)

    provider = JsonFileTestData()
    lease = provider.acquire(scope="run-1", scenarios=[])
    store.write_text(json.dumps({"seeded": True}))

    attestation = provider.release(lease)
    assert attestation.restored is True
    assert not store.exists()


def test_a_failed_restore_is_reported_as_residue(tmp_path, monkeypatch):
    """Silently leaving fixtures in a shared environment is the failure this
    exists to make visible."""
    from orchestrator import data_store
    from orchestrator.adapters import json_test_data

    store = tmp_path / "data-store.json"
    store.write_text(json.dumps({"a": 1}))
    monkeypatch.setattr(data_store, "DATA_STORE", store)
    monkeypatch.setattr(json_test_data, "DATA_STORE", store)

    provider = JsonFileTestData()
    lease = provider.acquire(scope="run-1", scenarios=[])

    # restore silently does nothing, as a partial failure would
    monkeypatch.setattr(data_store, "restore", lambda original: False)
    store.write_text(json.dumps({"a": 2}))

    attestation = provider.release(lease)
    assert attestation.restored is False
    assert attestation.residue == [str(store)]


def test_releasing_an_unknown_lease_says_so():
    provider = JsonFileTestData()
    out = provider.release(Lease(handle="never-acquired"))
    assert out.restored is False
    assert "nothing was acquired" in out.detail


# ── the runner keeps its results raw ──────────────────────────────────────


def test_the_runner_declares_itself():
    runner = PlaywrightRunner()
    assert runner.name == "playwright"
    assert runner.supports_parallel() is True
    assert runner.contract_version == EXECUTION_CONTRACT_VERSION


def test_a_missing_results_file_is_itself_a_result(tmp_path, monkeypatch):
    """Carrying the streams is what makes it diagnosable; returning an empty
    document would read to the gate as a run with no failures."""
    import subprocess

    from orchestrator.adapters import playwright_runner

    monkeypatch.setattr(playwright_runner, "RESULTS_FILE", tmp_path / "absent.json")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a, 1, stdout="out", stderr="boom"),
    )
    out = PlaywrightRunner().execute(specs=[], workers=1, env={}, evidence_dir=str(tmp_path))
    assert out["error"] == "no results.json produced"
    assert "boom" in out["stderr"]


def test_an_attestation_serialises_for_the_gate():
    body = Attestation("h", restored=False, verified=True, residue=["/tmp/x"]).as_dict()
    assert body["restored"] is False and body["residue"] == ["/tmp/x"]


# ── the provider for an app that mocks at the network boundary ────────────


MOCKS = """
export async function mockFroneiApi(page) {
  await page.route('http://127.0.0.1:8000/**', async route => {
    if (method === 'GET' && path === '/workspaces') return json(route, {})
    if (method === 'GET' && path === '/documents/templates') return json(route, {})
    if (path.startsWith('/admin/users')) return json(route, {})
  })
}
"""


def provider(tmp_path):
    from orchestrator.adapters.route_mock_test_data import RouteMockTestData

    f = tmp_path / "api-mocks.ts"
    f.write_text(MOCKS)
    return RouteMockTestData(f)


def test_route_mocks_give_per_scenario_isolation(tmp_path):
    """Playwright gives every test its own page, so the fixtures are
    per-test by construction. This is the first provider that can declare
    `scenario` honestly — not because the adapter is better, but because the
    application keeps its fixtures in version-controlled code rather than in
    mutable state."""
    from orchestrator.ports_execution import workers_for

    p = provider(tmp_path)
    assert p.isolation == "scenario"
    # Which the pipeline turns into parallelism, with no edit to the node.
    assert workers_for(p.isolation, True, mutating=True) == 0


def test_the_shape_is_read_from_the_mocks_not_declared_beside_them(tmp_path):
    """So it cannot claim an entity the handlers do not answer."""
    shape = provider(tmp_path).shape()
    assert "workspaces" in shape
    assert "templates" in shape
    assert "users" in shape
    assert "invoices" not in shape


def test_unknowable_fields_are_a_wildcard_not_an_empty_set(tmp_path):
    """A route handler returns whatever JSON its author wrote; inferring a
    schema from that would be guessing. An empty set is a different
    statement — "this entity has no fields" — which the gate reads as reject
    everything, turning missing information into a refusal."""
    from orchestrator.ports_execution import ANY_FIELD

    shape = provider(tmp_path).shape()
    assert shape["workspaces"] == {ANY_FIELD}
    assert shape["workspaces"] != set()


def test_nothing_is_seeded_and_nothing_is_restored(tmp_path):
    """And it says so, rather than reporting a restoration it did not
    perform. A provider claiming to have tidied up when there was nothing to
    tidy is indistinguishable from one that failed to."""
    p = provider(tmp_path)
    lease = p.acquire(scope="run-1", scenarios=[])
    assert lease.seeded == []

    out = p.release(lease)
    assert out.restored is True and out.verified is True
    assert out.residue == []
    assert "no state to restore" in out.detail


def test_a_missing_mock_file_yields_no_entities_rather_than_raising(tmp_path):
    """An application configured for route mocks that has not written them
    yet gates every scenario, which is the correct outcome — but it should
    not crash the plan phase to say so."""
    from orchestrator.adapters.route_mock_test_data import RouteMockTestData

    assert RouteMockTestData(tmp_path / "absent.ts").shape() == {}


# ── the runner actually narrows what it runs ──────────────────────────────


def _command(monkeypatch, *, specs, workers=1, project=""):
    """The argv the runner would execute, without executing it."""
    import orchestrator.adapters.playwright_runner as runner

    captured = {}

    class _Result:
        returncode = 0
        stdout = stderr = ""

    monkeypatch.setattr(
        runner.subprocess, "run",
        lambda command, **kw: (captured.setdefault("argv", command), _Result())[1],
    )
    monkeypatch.setenv("QA_PLAYWRIGHT_PROJECT", project)
    monkeypatch.setattr(runner, "RESULTS_FILE", Path("/nonexistent/results.json"))
    runner.PlaywrightRunner().execute(
        specs=specs, workers=workers, env={}, evidence_dir="/tmp"
    )
    return captured["argv"]


def test_the_assigned_specs_reach_the_command_line(monkeypatch):
    """They did not. The runner took `specs` and never used it, so Playwright
    collected whatever testDir held: the blast radius decided what was
    reported while the suite decided what was run, and "we selected these
    tests because of the impact" was not true of execution."""
    argv = _command(monkeypatch, specs=["e2e/generated/a.spec.ts", "e2e/b.spec.ts"])
    assert argv[-2:] == ["e2e/generated/a.spec.ts", "e2e/b.spec.ts"]


def test_one_project_unless_told_otherwise(monkeypatch):
    """Fronei declares chromium and mobile-chrome. An unqualified run executes
    every spec twice — twice the time, and authored scenarios graded against a
    viewport nobody wrote them for."""
    argv = _command(monkeypatch, specs=[], project="chromium")
    assert "--project=chromium" in argv

    unqualified = _command(monkeypatch, specs=[], project="")
    assert not any(a.startswith("--project") for a in unqualified)


def test_no_specs_means_the_suite_rather_than_nothing(monkeypatch):
    """An empty assignment list is a run with nothing to say, not a run that
    should silently execute every test in the repository — but Playwright's
    own default is the suite, and overriding that here would hide the
    difference between "nothing was assigned" and "everything ran"."""
    argv = _command(monkeypatch, specs=[])
    assert argv[:3] == ["npx", "playwright", "test"]
    assert not [a for a in argv if a.endswith(".spec.ts")]
