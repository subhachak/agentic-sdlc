"""Phase 5 — Execute. Runs the real Playwright suite against the running
app. This node does not judge pass/fail — it just runs and captures raw
results. Phase 7 (gate) makes the call.
"""
from __future__ import annotations

import json
import subprocess

from orchestrator.paths import APP_ROOT, EVIDENCE_DIR, RESULTS_FILE
from orchestrator.state import PipelineState


def run(state: PipelineState) -> PipelineState:
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)

    proc = subprocess.run(
        ["npx", "playwright", "test"],
        cwd=APP_ROOT,
        capture_output=True,
        text=True,
    )

    raw_results: dict = {}
    if RESULTS_FILE.exists():
        raw_results = json.loads(RESULTS_FILE.read_text())
    else:
        raw_results = {"error": "no results.json produced", "stdout": proc.stdout[-4000:], "stderr": proc.stderr[-4000:]}

    return {
        **state,
        "run_exit_code": proc.returncode,
        "run_results_raw": raw_results,
    }
