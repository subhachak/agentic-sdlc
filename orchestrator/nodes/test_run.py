"""Phase 5 — Execute. Runs the real Playwright suite against the running
app. This node does not judge pass/fail — it just runs and captures raw
results. Phase 7 (gate) makes the call.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from orchestrator.state import PipelineState

REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLE_APP = REPO_ROOT / "sample-app"
RESULTS_FILE = REPO_ROOT / "evidence" / "results.json"


def run(state: PipelineState) -> PipelineState:
    (REPO_ROOT / "evidence").mkdir(exist_ok=True)

    proc = subprocess.run(
        ["npx", "playwright", "test"],
        cwd=SAMPLE_APP,
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
