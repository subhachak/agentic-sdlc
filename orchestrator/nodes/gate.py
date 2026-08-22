"""Phase 7 — Gate: deterministic pass/fail. No LLM here, on principle.

gate_passed = every planned scenario has an assignment that ran
              AND every test result came back passed
              AND no scenario was dropped silently between plan and run
"""
from __future__ import annotations

from orchestrator.state import PipelineState


def _walk_results(node) -> list[dict]:
    """Flatten Playwright's nested JSON reporter output into a list of
    {title, status} leaves, regardless of suite nesting depth."""
    out: list[dict] = []
    if isinstance(node, dict):
        if "tests" in node:
            for t in node["tests"]:
                title = t.get("title", "?")
                results = t.get("results", [])
                status = results[-1]["status"] if results else "unknown"
                out.append({"title": title, "status": status})
        for key in ("suites",):
            for child in node.get(key, []):
                out.extend(_walk_results(child))
    return out


def run(state: PipelineState) -> PipelineState:
    reasons: list[str] = []
    raw = state.get("run_results_raw", {})

    if "error" in raw:
        return {
            **state,
            "gate_passed": False,
            "gate_reasons": [f"test run did not produce results: {raw['error']}"],
            "failing_scenarios": [s["id"] for s in state.get("test_plan", [])],
        }

    leaves = _walk_results(raw)
    failing = [l for l in leaves if l["status"] not in ("passed", "expected")]

    planned_count = len(state.get("test_plan", []))
    assigned_count = len(state.get("test_assignments", []))
    ran_count = len(leaves)

    if assigned_count < planned_count:
        reasons.append(f"only {assigned_count}/{planned_count} planned scenarios got a test assignment")
    if ran_count < assigned_count:
        reasons.append(f"only {ran_count}/{assigned_count} assigned tests actually ran")
    if failing:
        reasons.append(f"{len(failing)} test(s) failed: {[f['title'] for f in failing]}")

    gate_passed = not reasons

    return {
        **state,
        "gate_passed": gate_passed,
        "gate_reasons": reasons or ["all planned scenarios ran and passed"],
        "failing_scenarios": [f["title"] for f in failing],
    }
