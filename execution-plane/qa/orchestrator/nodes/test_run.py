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

from orchestrator import data_store
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


def run(state: PipelineState) -> PipelineState:
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)

    mutating = _mutating_specs(state)
    command = ["npx", "playwright", "test"]
    if mutating:
        # One worker. Slower, and the only honest option: these specs and
        # their neighbours share a store, and nothing here can give them a
        # private one without changing the application under test.
        command += ["--workers=1"]

    before = data_store.snapshot()
    proc = subprocess.run(
        command,
        cwd=APP_ROOT,
        capture_output=True,
        text=True,
    )
    after = data_store.snapshot()

    raw_results: dict = {}
    if RESULTS_FILE.exists():
        raw_results = json.loads(RESULTS_FILE.read_text())
    else:
        raw_results = {"error": "no results.json produced", "stdout": proc.stdout[-4000:], "stderr": proc.stderr[-4000:]}

    return {
        **state,
        "run_exit_code": proc.returncode,
        "run_results_raw": raw_results,
        "ran_serially": bool(mutating),
        "mutating_specs": mutating,
        # Measured, not assumed. A store that changed during the run means one
        # spec's data was visible to another, whatever the source analysis
        # concluded.
        "data_store_mutated": before != after,
    }
