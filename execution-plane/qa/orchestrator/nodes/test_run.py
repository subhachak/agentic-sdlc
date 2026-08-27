"""Phase 5 — Execute. Runs the real Playwright suite against the running
app. This node does not judge pass/fail — it just runs and captures raw
results. Phase 7 (gate) makes the call.

Parallelism is decided here rather than fixed in the config, because whether
it is sound depends on what this run's specs do. Every scenario shares one
data store; a spec that writes to it can change what a concurrently
executing spec reads. Restoring the store afterwards protects the checkout
and does nothing for correctness during the run.

The store is also compared before and after. Detection is worth having
alongside prevention: the analysis reads the spec source, and a mutation
routed some way it does not recognise would otherwise be invisible.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from orchestrator.adapters.json_test_data import JsonFileTestData
from orchestrator.adapters.playwright_runner import PlaywrightRunner
from orchestrator.ports_execution import workers_for
from orchestrator.paths import APP_ROOT, EVIDENCE_DIR, RESULTS_FILE
from orchestrator.state import PipelineState
from orchestrator.validate import mutates_shared_state


def _mutating_specs(state: PipelineState) -> dict[str, list[str]]:
    """Which assigned specs write, and with what verbs."""
    out: dict[str, list[str]] = {}
    for assignment in state.get("test_assignments", []):
        path = Path(assignment.get("file_path", ""))
        if not path.exists():
            continue
        verbs = mutates_shared_state(path.read_text(encoding="utf-8", errors="replace"))
        if verbs:
            out[assignment.get("scenario_id", path.name)] = verbs
    return out


def build_test_data_provider():
    """Which provider this deployment uses.

    A factory rather than a literal, for the same reason every other port
    has one: selecting a different implementation should be configuration,
    not an edit to the node that consumes it.

    Chosen by what the application under test actually does, not by a name.
    An app whose suite mocks at the network boundary has no store to seed,
    and pointing the JSON provider at a file that does not exist would make
    it report a restoration of nothing as though it meant something.
    """
    import os

    mocks = os.environ.get("QA_ROUTE_MOCKS")
    if mocks:
        from orchestrator.adapters.route_mock_test_data import RouteMockTestData

        return RouteMockTestData(mocks)
    return JsonFileTestData()


def build_test_runner():
    return PlaywrightRunner()


def _baseline(state: PipelineState, runner, workers: int) -> dict[str, str] | None:
    """How the required regression scripts behave *before* this change.

    Run against a checkout of the base revision, which the caller provides —
    this node will not go looking for one, because a base root it guessed at
    would silently produce a baseline for the wrong revision, and a wrong
    baseline is worse than none: it excuses real regressions.

    Returns None when no base checkout was supplied. The gate reads that as
    "nobody looked" rather than "nothing was already broken".
    """
    base_root = os.environ.get("QA_BASE_APP_ROOT", "")
    scope = state.get("regression_scope") or {}
    required = set(scope.get("required_scripts") or [])
    if not base_root or not required or not Path(base_root).is_dir():
        return None

    # Only the library scripts. Authored specs cannot have a baseline — they
    # did not exist at base — and asking for one would report every new
    # scenario as unexplained.
    specs = [
        a["file_path"]
        for a in state.get("test_assignments", [])
        if a.get("source_script_id") in required and a.get("file_path")
    ]
    if not specs:
        return None

    raw = runner.execute(
        specs=[Path(spec).name for spec in specs],
        workers=workers,
        env={},
        evidence_dir=str(EVIDENCE_DIR / "baseline"),
        app_root=Path(base_root),
    )
    if "error" in raw:
        # A baseline that could not run is not a baseline of passes.
        return None

    from orchestrator.nodes.gate import _basename, _walk_results, _PASSING

    by_spec: dict[str, list[str]] = {}
    for leaf in _walk_results(raw):
        by_spec.setdefault(_basename(leaf["file"]), []).append(leaf["status"])

    verdicts: dict[str, str] = {}
    for assignment in state.get("test_assignments", []):
        script_id = assignment.get("source_script_id")
        if script_id not in required:
            continue
        statuses = by_spec.get(_basename(assignment.get("file_path", "")))
        if not statuses:
            verdicts[script_id] = "missing"
        else:
            verdicts[script_id] = (
                "passed" if all(s in _PASSING for s in statuses) else "failed"
            )
    return verdicts


def run(state: PipelineState) -> PipelineState:
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)

    mutating = _mutating_specs(state)
    provider = build_test_data_provider()
    runner = build_test_runner()

    # Parallelism is now a function of two declarations rather than a
    # hardcoded `--workers=1`. A provider that can lease per scenario gets
    # concurrency without anyone editing this node.
    workers = workers_for(provider.isolation, runner.supports_parallel(), bool(mutating))

    lease = provider.acquire(scope=state.get("run_id") or "run", scenarios=state.get("scenarios") or [])
    try:
        raw_results = runner.execute(
            specs=state.get("spec_files") or [],
            workers=workers,
            env=lease.env,
            evidence_dir=str(EVIDENCE_DIR),
        )
    finally:
        # Always, including when the runner raised. A teardown that only
        # happens on the happy path is a teardown that does not happen on
        # the day it matters.
        attestation = provider.release(lease)

    return {
        **state,
        # What the required set does without this change. Captured after the
        # head run rather than before, so a baseline failure never prevents
        # the run that actually matters from happening.
        "baseline_verdicts": _baseline(state, runner, workers),
        "run_exit_code": raw_results.get("exit_code", 0) if "error" in raw_results else 0,
        "run_results_raw": raw_results,
        "ran_serially": workers == 1,
        "mutating_specs": mutating,
        # Claimed *and* checked. "We ran the restore code" and "the store is
        # as it was" are different claims, and only the second is evidence.
        "test_data_attestation": attestation.as_dict(),
        # Kept for the gate, which reads it as "one spec's data was visible
        # to another". Now derived from the provider's own verification
        # rather than from a snapshot comparison in this node.
        "data_store_mutated": not attestation.restored,
    }
