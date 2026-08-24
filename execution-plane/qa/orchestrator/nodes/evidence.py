"""Phase 6 — Evidence: point to what execution produced. Doesn't move or
duplicate artifacts, just indexes them so the report node and the gate
node both work from one summary.
"""
from __future__ import annotations


from orchestrator.paths import CHECKOUT_ROOT, EVIDENCE_DIR
from orchestrator.coverage import coverage_by_spec, coverage_gaps, reconcile_declared
from orchestrator.promotion import candidates
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

    # What each spec actually exercised, read from the traces this phase is
    # already collecting. `covers_modules` in the manifest is a claim; this is
    # the run's own account of which files it reached.
    observed = coverage_by_spec(state.get("run_results_raw") or {})
    mismatches = reconcile_declared(observed, state.get("test_assignments", []))

    return {
        **state,
        "evidence_summary": summary,
        "observed_coverage": observed,
        "coverage_mismatches": mismatches,
        "coverage_gaps_observed": coverage_gaps(observed),
        "promotion_candidates": candidates(
            {**state, "observed_coverage": observed}
        ),
    }
