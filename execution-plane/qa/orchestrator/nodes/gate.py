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

import json
import os

from orchestrator.baseline import compare
from orchestrator.known_failing import assess as assess_known_failing
from orchestrator.known_failing import load as load_known_failing
from orchestrator.paths import EVIDENCE_DIR, KNOWN_FAILING_FILE
from orchestrator.state import PipelineState

# Playwright test-level statuses that count as a clean pass. Anything else
# ("unexpected", "flaky", "skipped") is not a scenario we can claim ran and
# passed, so it belongs in the gate reasons.
_PASSING = ("expected", "passed")


def _require_green_baseline() -> bool:
    """No admitted debt at all — for a suite that is green and staying that
    way. The ratchet's destination, available to anyone already there."""
    return os.environ.get("QA_REQUIRE_GREEN_BASELINE", "") not in ("", "0", "false")


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


def _covered_modules(state: PipelineState, leaves: list[dict]) -> list[str]:
    """Which modules this run actually exercised, and can prove it did.

    The platform hands down a blast radius and reconciles it against this,
    so what goes here has to be what happened rather than what was planned.
    Two rules follow from that.

    Only passing tests count. A spec that ran and failed demonstrates the
    opposite of coverage, and counting it would let a broken change report
    its blast radius as covered.

    Observation beats declaration. `covers_modules` in a manifest is
    somebody's assertion; the files a spec actually requested are the run's
    own account. The manifest is the fallback for a run with no traces, and
    the two are not interchangeable — which is why the graph edges written
    from this carry `runtime-observed` or `declared` rather than neither.
    """
    from orchestrator.context import _load_manifest, modules_for_paths

    passed_files = {
        _basename(leaf["file"]) for leaf in leaves if leaf["status"] in _PASSING
    }
    failed_files = {
        _basename(leaf["file"]) for leaf in leaves if leaf["status"] not in _PASSING
    }
    # A spec with any failing case proves nothing about the modules it
    # touched, even if its other cases passed.
    proven = passed_files - failed_files

    observed = state.get("observed_coverage") or {}
    modules: set[str] = set()
    for name, entry in observed.items():
        if _basename(name) in proven:
            modules |= modules_for_paths(entry.get("files") or [])

    # Fallback for an assignment that produced no trace: the manifest's
    # claim, but only for a script that demonstrably passed.
    manifest = {e.get("id"): e for e in _load_manifest()}
    for assignment in state.get("test_assignments", []):
        script_id = assignment.get("source_script_id")
        spec = _basename(assignment.get("file_path", ""))
        if spec not in proven or script_id not in manifest:
            continue
        if _basename(spec) in {_basename(n) for n in observed}:
            continue
        modules |= set(manifest[script_id].get("covers_modules") or [])

    return sorted(modules)


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

    # Not failures. A stale or hand-maintained graph still scopes better than
    # none, and refusing the run would make an out-of-date export worse than
    # never having generated one. Reported so the scoping is qualified rather
    # than presented as certain.
    graph_notes = list(scope.get("graph_warnings") or [])

    # A script that passed while never requesting the module it claims to
    # cover is a coverage record a gate will trust and that is not true.
    # Failing closed here is the difference between measured coverage and a
    # comment in a JSON file.
    mismatches = state.get("coverage_mismatches") or []
    if mismatches:
        reasons.extend(mismatches)

    # A store that changed during the run means one spec's data was visible
    # to another. Fails closed: every assertion in the run was made against
    # data that something else may have been changing underneath it, so a
    # pass proves nothing in particular.
    if state.get("data_store_mutated") and not state.get("ran_serially"):
        reasons.append(
            "the shared data store changed during a parallel run — one scenario's "
            "writes were visible to others, so these results are not trustworthy"
        )

    never_ran, required_failed = _required_verdicts(state, leaves)

    # Which of those failures this change is answerable for. A suite red
    # before the change is red because of something else, and blocking on it
    # means a codebase with any pre-existing failure can never merge
    # anything — the same reasoning that already makes coverage gaps report
    # rather than block.
    differential = compare(
        required_failed,
        sorted(scope.get("required_scripts") or []),
        state.get("baseline_verdicts"),
    )
    # Debt has to be declared, and the declaration may not grow. Without
    # this the differential is a permanent excuse: the pre-existing list
    # could grow forever and nothing would notice, so attribution quietly
    # becomes tolerance and the suite rots at the speed nobody measures.
    ratchet = assess_known_failing(
        state.get("baseline_verdicts"),
        load_known_failing(KNOWN_FAILING_FILE),
        strict=_require_green_baseline(),
    )
    # A pre-existing failure is only excused if it was admitted to. One that
    # was not is a failure somebody merged without writing it down, which is
    # the growth this exists to stop.
    if ratchet.established:
        undeclared = set(ratchet.grew)
        differential.pre_existing = [
            s for s in differential.pre_existing if s not in undeclared
        ]
        differential.regressions = sorted(set(differential.regressions) | undeclared)

    # Written where CI uploads it, so adopting the record — or shrinking it —
    # is one file somebody copies rather than a list they retype off a log.
    # Never written into the repository: a pipeline that recorded its own
    # accepted failures would ratchet in the wrong direction on its first run
    # and call it a baseline.
    if ratchet.proposal or ratchet.stale:
        EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
        (EVIDENCE_DIR / "known-failing.proposed.json").write_text(
            json.dumps({"known_failing": ratchet.proposal}, indent=2) + "\n"
        )

    required_failed = differential.blocking

    # A pre-existing failure must not come back through the general failing
    # check. It did: the differential excused it, the note said "not blocking
    # it", and the gate failed anyway on the same result — a verdict that
    # contradicted its own explanation, which is worse than either answer on
    # its own.
    excused_specs = {
        _basename(assignment.get("file_path", ""))
        for assignment in state.get("test_assignments", [])
        if assignment.get("source_script_id") in set(differential.pre_existing)
    }
    failing = [f for f in failing if _basename(f["file"]) not in excused_specs]

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
    notes = [*notes, *(f"note: {w}" for w in graph_notes)]
    if state.get("ran_serially"):
        notes = [
            *notes,
            "note: ran with one worker because "
            + ", ".join(
                f"{scenario} issues {'/'.join(verbs)}"
                for scenario, verbs in (state.get("mutating_specs") or {}).items()
            )
            + " — scenarios share one data store, so parallel execution would let "
            "one scenario's writes change what another reads",
        ]
    if differential.pre_existing:
        notes = [
            *notes,
            f"note: {len(differential.pre_existing)} required script(s) were already "
            f"failing before this change and are not blocking it: "
            + ", ".join(differential.pre_existing),
        ]
    if ratchet.grew:
        notes = [
            *notes,
            "the set of accepted failures grew: "
            + ", ".join(ratchet.grew)
            + " failed before this change but was never written down. Fix it, or "
            "add it to known-failing.json where somebody reviews the decision.",
        ]
    if ratchet.stale:
        notes = [
            *notes,
            "note: no longer failing and can be struck from known-failing.json: "
            + ", ".join(ratchet.stale),
        ]
    if not ratchet.established and ratchet.proposal:
        notes = [
            *notes,
            "note: no known-failing.json, so growth in accepted failures is not "
            "measured. A record containing "
            + ", ".join(ratchet.proposal)
            + " would start the ratchet.",
        ]
    if differential.repaired:
        notes = [*notes, "note: this change repairs " + ", ".join(differential.repaired)]
    if required_failed and not differential.established:
        notes = [
            *notes,
            "note: no baseline was established, so every failing required script "
            "blocks — set QA_BASE_APP_ROOT to a checkout of the base revision to "
            "tell a regression from a pre-existing failure",
        ]
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
        "graph_warnings": graph_notes,
        # What was already broken, so a release decision can tell "this
        # change broke it" from "this was broken when we got here" without
        # reading two test reports side by side.
        "regression_differential": differential.as_dict(),
        # What was admitted, what grew, and what is now fixed and can be
        # struck off. The record shrinking is the only direction this is
        # allowed to move without somebody deciding.
        "known_failing": ratchet.as_dict(),
        # The accounting the control plane reconciles against the blast
        # radius it handed down. Reported rather than compared here: this
        # plane knows what it exercised, the platform knows what it obliged,
        # and a provider that graded its own obligation would be marking its
        # own homework.
        #
        # The two lists say different things. `covered` is a demonstration;
        # `uncovered` is a disclosure — impacted modules this run knows it
        # could not cover, which is a materially better answer than leaving
        # them unmentioned and is scored as such.
        "covered_modules": _covered_modules(state, leaves),
        "uncovered_modules": sorted(uncovered),
    }
