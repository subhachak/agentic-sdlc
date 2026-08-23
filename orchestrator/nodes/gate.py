"""Phase 7 — Gate: deterministic pass/fail. No LLM here, on principle.

gate_passed = every planned scenario has an assignment that ran
              AND every test result came back passed
              AND no scenario was dropped silently between plan and run
"""
from __future__ import annotations

from orchestrator.state import PipelineState

# Playwright test-level statuses that count as a clean pass. Anything else
# ("unexpected", "flaky", "skipped") is not a scenario we can claim ran and
# passed, so it belongs in the gate reasons.
_PASSING = ("expected", "passed")


def _walk_results(node) -> list[dict]:
    """Flatten Playwright's JSON reporter output into a list of
    {title, status} leaves, regardless of suite nesting depth.

    The reporter nests as suites[] -> specs[] -> tests[] -> results[]. The
    human-readable title lives on the *spec*; the resolved pass/fail verdict
    (after retries) lives on the *test* as `status`. Nested describe blocks
    appear as child `suites` on a suite, so recurse through those too.
    """
    out: list[dict] = []
    if not isinstance(node, dict):
        return out

    for spec in node.get("specs", []):
        title = spec.get("title", "?")
        for test in spec.get("tests", []):
            status = test.get("status")
            if status is None:
                results = test.get("results", [])
                status = results[-1].get("status", "unknown") if results else "unknown"
            out.append({"title": title, "status": status})

    for child in node.get("suites", []):
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
    failing = [l for l in leaves if l["status"] not in _PASSING]

    # A spec refused by orchestrator/validate.py never ran. Say so explicitly,
    # otherwise the only symptom is an unexplained assignment-count shortfall.
    reasons.extend(state.get("generation_rejections", []))

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
