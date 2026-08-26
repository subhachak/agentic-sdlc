"""Test data and test execution as ports, and what they now have to say.

Neither existed. Test data was a module reading one JSON file, called
directly from two nodes; execution was `subprocess.run(["npx","playwright"])`
written into a third. Both are good defaults and neither was replaceable, so
a client whose fixtures live in Postgres or whose suite is Cypress had to
fork the pipeline.
"""

from __future__ import annotations

import json

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
