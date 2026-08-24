"""Phase 7 — Gate: deterministic pass/fail. No LLM here, on principle.

gate_passed = every planned scenario has an assignment that ran
              AND every required regression script ran and passed
              AND every test result came back passed
              AND no scenario was dropped silently between plan and run

The required-regression check is the one the blast radius exists for. Before
it, impacted modules and the scenarios covering them were interpolated into
the planning prompt and nothing verified the result — an agent could omit
every regression candidate and still pass this gate, which made the scoping
a narrative rather than a control.

Coverage gaps are reported but do not fail by default. An impacted module
that no script covers is a real risk and a real answer for a release
decision, but refusing every such change would refuse every change to a
codebase that has not finished building a regression suite. Set
QA_REQUIRE_FULL_COVERAGE=1 to make it blocking, which is the setting a team
ratchets once its library has caught up.
"""
from __future__ import annotations

import os

from orchestrator.state import PipelineState

# Playwright test-level statuses that count as a clean pass. Anything else
# ("unexpected", "flaky", "skipped") is not a scenario we can claim ran and
# passed, so it belongs in the gate reasons.
_PASSING = ("expected", "passed")


def _require_full_coverage() -> bool:
    return os.environ.get("QA_REQUIRE_FULL_COVERAGE", "").strip().lower() in ("1", "true", "yes")


def _walk_results(node, file: str = "") -> list[dict]:
    """Flatten Playwright's JSON reporter output into a list of
    {title, status, file} leaves, regardless of suite nesting depth.

    The reporter nests as suites[] -> specs[] -> tests[] -> results[]. The
    human-readable title lives on the *spec*; the resolved pass/fail verdict
    (after retries) lives on the *test* as `status`. Nested describe blocks
    appear as child `suites` on a suite, so recurse through those too.

    The file travels down with each leaf because a title cannot identify
    which assignment produced a result — two scenarios can title their test
    identically, and a required regression must be traceable to its own spec
    rather than to a string that happens to match.
    """
    out: list[dict] = []
    if not isinstance(node, dict):
        return out

    file = node.get("file") or file
    for spec in node.get("specs", []):
        title = spec.get("title", "?")
        spec_file = spec.get("file") or file
        for test in spec.get("tests", []):
            status = test.get("status")
            if status is None:
                results = test.get("results", [])
                status = results[-1].get("status", "unknown") if results else "unknown"
            out.append({"title": title, "status": status, "file": spec_file})

    for child in node.get("suites", []):
        out.extend(_walk_results(child, file))

    return out


def _basename(path: str) -> str:
    return (path or "").replace("\\", "/").rsplit("/", 1)[-1]


def _required_verdicts(state: PipelineState, leaves: list[dict]) -> tuple[list[str], list[str]]:
    """Which required regression scripts ran, and which of those passed.

    Matched on spec filename rather than on the reporter's `file`, which is
    project-relative and so is not the absolute path the assignment recorded.
    """
    scope = state.get("regression_scope") or {}
    required = set(scope.get("required_scripts") or [])
    if not required:
        return [], []

    by_file: dict[str, list[dict]] = {}
    for leaf in leaves:
        by_file.setdefault(_basename(leaf["file"]), []).append(leaf)

    never_ran: list[str] = []
    failed: list[str] = []
    for assignment in state.get("test_assignments", []):
        script_id = assignment.get("source_script_id")
        if script_id not in required:
            continue
        results = by_file.get(_basename(assignment.get("file_path", "")))
        if not results:
            never_ran.append(script_id)
        elif any(r["status"] not in _PASSING for r in results):
            failed.append(script_id)

    covered = {
        a.get("source_script_id")
        for a in state.get("test_assignments", [])
        if a.get("source_script_id") in required
    }
    never_ran.extend(sorted(required - covered))
    return sorted(set(never_ran)), sorted(set(failed))


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

    scope = state.get("regression_scope") or {}
    dangling = scope.get("dangling_coverage") or []
    if dangling:
        # A module claiming coverage from a script that does not exist. Fails
        # closed: the alternative is a run that reports a clean regression
        # sweep over a set that resolved to nothing.
        reasons.append(
            "the code graph claims coverage from scripts that do not exist: "
            + ", ".join(dangling)
        )

    never_ran, required_failed = _required_verdicts(state, leaves)
    if never_ran:
        reasons.append(
            "required regression scripts did not run: " + ", ".join(never_ran)
        )
    if required_failed:
        reasons.append(
            "required regression scripts failed: " + ", ".join(required_failed)
        )

    # Assignments include the required regressions, which are not planned
    # scenarios — comparing the two counts directly would report a shortfall
    # that does not exist.
    planned_count = len(state.get("test_plan", []))
    assignments = state.get("test_assignments", [])
    planned_assigned = len([a for a in assignments if a.get("mode") != "required-regression"])
    ran_count = len(leaves)

    if planned_assigned < planned_count:
        reasons.append(
            f"only {planned_assigned}/{planned_count} planned scenarios got a test assignment"
        )
    if ran_count < len(assignments):
        reasons.append(f"only {ran_count}/{len(assignments)} assigned tests actually ran")
    if failing:
        reasons.append(f"{len(failing)} test(s) failed: {[f['title'] for f in failing]}")

    uncovered = scope.get("uncovered_components") or []
    coverage_gap = (
        "impacted modules with no regression script: " + ", ".join(uncovered)
        if uncovered
        else ""
    )
    if coverage_gap and _require_full_coverage():
        reasons.append(coverage_gap)

    gate_passed = not reasons
    notes = reasons or ["all planned scenarios ran and passed"]
    if coverage_gap and not _require_full_coverage():
        # Reported whether or not it blocks. "We did not test this" is the
        # answer a release decision needs; silence is not.
        notes = [*notes, f"note: {coverage_gap} (not blocking — set QA_REQUIRE_FULL_COVERAGE=1)"]

    return {
        **state,
        "gate_passed": gate_passed,
        "gate_reasons": notes,
        "failing_scenarios": [f["title"] for f in failing],
        "required_regressions": sorted(scope.get("required_scripts") or []),
        "required_regressions_failed": required_failed,
        "required_regressions_missing": never_ran,
        "coverage_gaps": sorted(uncovered),
    }
