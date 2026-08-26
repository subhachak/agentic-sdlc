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
    """
    return JsonFileTestData()


def build_test_runner():
    return PlaywrightRunner()


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
