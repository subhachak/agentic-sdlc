"""Phase 6 — Evidence: point to what execution produced. Doesn't move or
duplicate artifacts, just indexes them so the report node and the gate
node both work from one summary.
"""
from __future__ import annotations

from pathlib import Path

from orchestrator.state import PipelineState

REPO_ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_DIR = REPO_ROOT / "evidence"


def run(state: PipelineState) -> PipelineState:
    test_results_dir = EVIDENCE_DIR / "test-results"
    screenshots = list(test_results_dir.rglob("*.png")) if test_results_dir.exists() else []
    traces = list(test_results_dir.rglob("*.zip")) if test_results_dir.exists() else []
    html_report = EVIDENCE_DIR / "html-report" / "index.html"

    summary = {
        "html_report": str(html_report) if html_report.exists() else None,
        "screenshot_count": len(screenshots),
        "trace_count": len(traces),
        "screenshots": [str(p) for p in screenshots],
        "traces": [str(p) for p in traces],
    }

    return {**state, "evidence_summary": summary}
