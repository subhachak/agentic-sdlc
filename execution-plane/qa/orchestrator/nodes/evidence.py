"""Phase 6 — Evidence: point to what execution produced. Doesn't move or
duplicate artifacts, just indexes them so the report node and the gate
node both work from one summary.
"""
from __future__ import annotations


from orchestrator.paths import CHECKOUT_ROOT, EVIDENCE_DIR
from orchestrator.state import PipelineState


def run(state: PipelineState) -> PipelineState:
    test_results_dir = EVIDENCE_DIR / "test-results"
    screenshots = list(test_results_dir.rglob("*.png")) if test_results_dir.exists() else []
    traces = list(test_results_dir.rglob("*.zip")) if test_results_dir.exists() else []
    html_report = EVIDENCE_DIR / "html-report" / "index.html"

    def rel(path: Path) -> str:
        # Relative to the checkout under test, not the repository root: a run
        # against a branch produces its evidence beside that checkout.
        return str(path.relative_to(CHECKOUT_ROOT))

    summary = {
        "html_report": rel(html_report) if html_report.exists() else None,
        "screenshot_count": len(screenshots),
        "trace_count": len(traces),
        "screenshots": [rel(p) for p in screenshots],
        "traces": [rel(p) for p in traces],
    }

    return {**state, "evidence_summary": summary}
