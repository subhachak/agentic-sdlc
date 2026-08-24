"""Turning a run's generated specs into durable library scripts.

The structural weakness this addresses: generated specs were written, run
once, and deleted. `_clear_generated_dir()` wipes the directory at the start
of every run, so the suite never accumulated — which is why the library held
a single script until someone wrote two more by hand. The pipeline spent a
model call per scenario per run re-deriving tests it had already written and
thrown away.

Promotion inverts that. A generated spec that passed is a candidate to become
a committed library script, with `covers_modules` taken from what the run
observed it exercise rather than from what anyone claims about it.

This proposes; it does not commit. The job that executes agent-written code
deliberately holds no write token — that is the containment the whole
execution plane is built around, and a node that could write to the
repository would dissolve it. Candidates are emitted as evidence, reported on
the pull request, and applied by scripts/promote.py under whatever review the
client already runs.
"""

from __future__ import annotations

from typing import Any

from orchestrator.context import _load_manifest


def _library_modules() -> set[str]:
    return {m for e in _load_manifest() for m in e.get("covers_modules") or []}


def _slug(text: str) -> str:
    cleaned = "".join(c if c.isalnum() else "-" for c in (text or "").lower())
    return "-".join(part for part in cleaned.split("-") if part) or "scenario"


def candidates(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Passing generated specs worth keeping, best reason first.

    Every passing generated spec is offered, not only the ones that close a
    coverage gap: a second scenario against an already-covered module is
    often the more valuable test, and that is a judgement deterministic code
    should not be making on its own. What the code does decide is which ones
    demonstrably widen module coverage, because that is checkable.
    """
    observed = state.get("observed_coverage") or {}
    covered = _library_modules()
    existing_ids = {e.get("id") for e in _load_manifest()}
    plan = {s.get("id"): s for s in state.get("test_plan", [])}

    out: list[dict[str, Any]] = []
    for assignment in state.get("test_assignments", []):
        if assignment.get("mode") != "generated":
            continue

        name = (assignment.get("file_path") or "").replace("\\", "/").rsplit("/", 1)[-1]
        seen = observed.get(name)
        if not seen or not seen.get("passed") or not seen.get("modules"):
            continue

        scenario_id = assignment.get("scenario_id", "")
        scenario = plan.get(scenario_id) or {}
        new_modules = sorted(set(seen["modules"]) - covered)
        script_id = _slug(scenario_id)
        if script_id in existing_ids:
            continue  # already promoted under this name by an earlier run

        out.append(
            {
                "script_id": script_id,
                "from_scenario": scenario_id,
                "spec_path": assignment.get("file_path"),
                "route": scenario.get("target_route", ""),
                "covers": scenario.get("expected_outcome", ""),
                "ac_ref": scenario.get("ac_ref", ""),
                # Observed, not declared. The whole point.
                "covers_modules": seen["modules"],
                "requests": seen.get("requests", []),
                "closes_coverage_gap": bool(new_modules),
                "new_modules": new_modules,
            }
        )

    return sorted(out, key=lambda c: (not c["closes_coverage_gap"], c["script_id"]))


def manifest_entry(candidate: dict[str, Any]) -> dict[str, Any]:
    """The manifest row a promoted candidate becomes."""
    return {
        "id": candidate["script_id"],
        "file": f"{candidate['script_id']}.spec.ts",
        "route": candidate.get("route", ""),
        "tags": sorted({t for t in _slug(candidate["from_scenario"]).split("-") if len(t) > 2}),
        "covers": candidate.get("covers", ""),
        "covers_modules": candidate["covers_modules"],
        "promoted_from_run": candidate.get("run", ""),
        "coverage_provenance": "runtime-observed",
    }
