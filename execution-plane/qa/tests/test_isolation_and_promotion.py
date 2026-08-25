"""Four gaps a review found in the run-level cleanup.

Restoring the store after a run protects the checkout; it is not test
isolation. Counting every traced request as coverage credits handlers that
never ran. A candidate referenced by path is gone once the runner is. And a
store that did not exist before was not restored to not existing.
"""

from __future__ import annotations

import hashlib
import json
import zipfile

import pytest

from orchestrator import data_store
from orchestrator.coverage import intercepted_paths, request_paths, traced_requests
from orchestrator.promotion import MAX_SPEC_BYTES, verify
from orchestrator.validate import mutates_shared_state


def _trace(tmp_path, *entries):
    """entries: (method, url, fulfilled)"""
    path = tmp_path / "trace.zip"
    lines = "\n".join(
        json.dumps(
            {
                "type": "resource-snapshot",
                "snapshot": {
                    "request": {"method": m, "url": u},
                    **({"_wasFulfilled": True} if fulfilled else {}),
                },
            }
        )
        for m, u, fulfilled in entries
    )
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("0-trace.network", lines)
    return path


# --- 1. interception is not coverage ---------------------------------------


def test_an_intercepted_request_is_not_counted_as_coverage(tmp_path):
    """The test answered it; the handler never ran. Crediting it would put a
    claim in the manifest that reconciliation can never detect as false,
    because the interception happens on every run."""
    trace = _trace(
        tmp_path,
        ("GET", "http://localhost:3000/claims", False),
        ("GET", "http://localhost:3000/api/claims?status=Denied", True),
    )

    assert request_paths(trace) == {("GET", "/claims")}
    assert intercepted_paths(trace) == {("GET", "/api/claims")}


def test_a_served_request_is_still_counted(tmp_path):
    trace = _trace(tmp_path, ("GET", "http://localhost:3000/api/claims", False))
    assert request_paths(trace) == {("GET", "/api/claims")}


def test_the_same_path_served_once_and_intercepted_once_still_counts(tmp_path):
    """A spec whose other tests genuinely hit the endpoint does cover it. Only
    the interception itself earns nothing."""
    trace = _trace(
        tmp_path,
        ("GET", "http://localhost:3000/api/claims", False),
        ("GET", "http://localhost:3000/api/claims?status=Denied", True),
    )
    assert ("GET", "/api/claims") in request_paths(trace)


def test_the_interception_is_reported_rather_than_dropped(tmp_path):
    """It is the reason a test does not cover something, and a reader
    comparing a coverage gap against the tests that exist needs to see it."""
    trace = _trace(tmp_path, ("GET", "http://localhost:3000/api/claims", True))
    marked = {r.path: r.fulfilled for r in traced_requests(trace)}

    assert marked == {"/api/claims": True}


# --- 2. a candidate survives the runner ------------------------------------


def _candidate(source: str, **overrides):
    raw = source.encode("utf-8")
    return {
        "script_id": "s1",
        "source": source,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw),
        **overrides,
    }


def test_a_candidate_carrying_its_source_verifies():
    assert verify(_candidate("import { test } from '@playwright/test';\ntest('x', async () => {});\n")) is None


def test_a_candidate_with_no_source_is_refused():
    """The failure this replaces: a path into `generated-tests` on a runner
    that no longer exists."""
    assert "carries no source" in verify({"script_id": "s1"})


def test_a_tampered_candidate_is_refused():
    """It has travelled through a state file and an artifact upload since
    anything last looked at it."""
    candidate = _candidate("import { test } from '@playwright/test';\ntest('x', async () => {});\n")
    candidate["source"] = candidate["source"] + "// changed\n"

    assert "checksum mismatch" in verify(candidate)


def test_a_candidate_that_would_not_pass_the_sandbox_is_refused():
    """Re-validated at promotion time: a library script runs against every
    future change that reaches its modules."""
    candidate = _candidate("import fs from 'node:fs';\ntest('x', async () => {});\n")
    assert "Node builtin" in verify(candidate)


def test_the_size_cap_is_a_real_limit():
    assert MAX_SPEC_BYTES == 64 * 1024


# --- 3. parallel execution is unsound when a spec writes -------------------


@pytest.mark.parametrize(
    "code,expected",
    [
        ("await request.get('/api/claims')", []),
        ("await request.post('/api/claims', { data: x })", ["POST"]),
        ("await page.request.delete('/api/claims/1')", ["DELETE"]),
        ("await request.fetch(url, { method: 'PUT' })", ["PUT"]),
        ("await request.fetch('/api/claims')", []),
    ],
)
def test_mutating_calls_are_detected_however_they_are_written(code, expected):
    """Detected from the source rather than declared, because what a generated
    spec actually does is what matters."""
    assert mutates_shared_state(code) == expected


def test_a_run_with_a_mutating_spec_gives_up_parallelism(tmp_path, monkeypatch):
    import orchestrator.nodes.test_run as test_run

    spec = tmp_path / "writes.spec.ts"
    spec.write_text("await request.post('/api/claims', { data: {} })")

    mutating = test_run._mutating_specs(
        {"test_assignments": [{"scenario_id": "s1", "file_path": str(spec)}]}
    )

    assert mutating == {"s1": ["POST"]}


def test_a_read_only_run_keeps_its_parallelism(tmp_path):
    import orchestrator.nodes.test_run as test_run

    spec = tmp_path / "reads.spec.ts"
    spec.write_text("await request.get('/api/claims')")

    assert test_run._mutating_specs(
        {"test_assignments": [{"scenario_id": "s1", "file_path": str(spec)}]}
    ) == {}


def test_a_store_that_changed_during_a_parallel_run_fails_the_gate():
    """Measured, not assumed. Every assertion in the run was made against data
    something else may have been changing underneath it."""
    from orchestrator.nodes.gate import run as gate

    result = gate({
        "test_plan": [],
        "test_assignments": [],
        "regression_scope": {},
        "run_results_raw": {"config": {}, "suites": [], "errors": []},
        "data_store_mutated": True,
        "ran_serially": False,
    })

    assert result["gate_passed"] is False
    assert any("changed during a parallel run" in r for r in result["gate_reasons"])


def test_a_store_that_changed_during_a_serial_run_is_not_a_failure():
    from orchestrator.nodes.gate import run as gate

    result = gate({
        "test_plan": [],
        "test_assignments": [],
        "regression_scope": {},
        "run_results_raw": {"config": {}, "suites": [], "errors": []},
        "data_store_mutated": True,
        "ran_serially": True,
        "mutating_specs": {"s1": ["POST"]},
    })

    assert result["gate_passed"] is True
    assert any("one worker" in r for r in result["gate_reasons"])


# --- 4. restoring "absent" means absent ------------------------------------


def test_a_store_the_run_created_is_removed_again(tmp_path, monkeypatch):
    """A provider that creates its store during setup would otherwise leave
    the file behind, and the next run would seed on top of it believing it
    was the application's own data."""
    store = tmp_path / "data-store.json"
    monkeypatch.setattr(data_store, "DATA_STORE", store)

    original = data_store.snapshot()
    assert original is None

    store.write_text('{"claims": []}')
    assert data_store.restore(original) is True
    assert not store.exists()


def test_restoring_an_unchanged_store_is_a_no_op(tmp_path, monkeypatch):
    store = tmp_path / "data-store.json"
    store.write_text('{"claims": []}')
    monkeypatch.setattr(data_store, "DATA_STORE", store)

    assert data_store.restore(data_store.snapshot()) is False


def test_a_store_that_never_existed_and_still_does_not_needs_no_change(tmp_path, monkeypatch):
    monkeypatch.setattr(data_store, "DATA_STORE", tmp_path / "absent.json")
    assert data_store.restore(None) is False
