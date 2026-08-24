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

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from orchestrator.context import _load_manifest, graph_project
from orchestrator.validate import validate_spec

# A spec is a test file, not a payload. Anything larger is either generated
# noise or something that should be reviewed as a pull request rather than
# carried inside a JSON state file.
MAX_SPEC_BYTES = 64 * 1024


def _library_modules() -> set[str]:
    return {m for e in _load_manifest() for m in e.get("covers_modules") or []}


def _slug(text: str) -> str:
    cleaned = "".join(c if c.isalnum() else "-" for c in (text or "").lower())
    return "-".join(part for part in cleaned.split("-") if part) or "scenario"


def _bundle(spec_path: str) -> dict[str, Any] | None:
    """The spec's actual source, with a checksum.

    Carried in the candidate rather than referenced by path. The job that
    generated it is a CI runner that disappears when the workflow ends, and
    only the state file and the evidence directory are uploaded — so a path
    into `generated-tests` is dead by the time anyone reads the candidate.
    """
    path = Path(spec_path or "")
    if not path.exists():
        return None
    source = path.read_text(encoding="utf-8", errors="replace")
    raw = source.encode("utf-8")
    if len(raw) > MAX_SPEC_BYTES:
        return None
    return {
        "source": source,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw),
    }


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

        bundle = _bundle(assignment.get("file_path", ""))
        if bundle is None:
            continue  # unreadable or too large to carry; nothing to promote

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
                "intercepted": seen.get("intercepted", []),
                "closes_coverage_gap": bool(new_modules),
                "new_modules": new_modules,
                # The file itself, so this survives the runner.
                **bundle,
                # Where it came from, so a reviewer can tell what they are
                # being asked to take into a library that runs against every
                # future change.
                "provenance": {
                    "run": f"{state.get('repo', 'local')}#{state.get('pr_number', 0)}",
                    "head_sha": state.get("head_sha"),
                    "graph_project": graph_project(),
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                    "spec_path": assignment.get("file_path"),
                    "ran_serially": bool(state.get("ran_serially")),
                },
            }
        )

    return sorted(out, key=lambda c: (not c["closes_coverage_gap"], c["script_id"]))


def verify(candidate: dict[str, Any]) -> str | None:
    """Why this candidate must not be promoted, or None.

    Re-checked at promotion time rather than trusted from generation: the
    candidate has travelled through a state file and an artifact upload since
    anything last looked at it, and a library script runs against every future
    change that reaches its modules.
    """
    source = candidate.get("source")
    if not source:
        return "carries no source"

    digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
    if digest != candidate.get("sha256"):
        return f"checksum mismatch: recorded {candidate.get('sha256')}, source hashes to {digest}"

    violations = validate_spec(source)
    if violations:
        return "; ".join(violations)
    return None


def manifest_entry(candidate: dict[str, Any]) -> dict[str, Any]:
    """The manifest row a promoted candidate becomes."""
    return {
        "id": candidate["script_id"],
        "file": f"{candidate['script_id']}.spec.ts",
        "route": candidate.get("route", ""),
        "tags": sorted({t for t in _slug(candidate["from_scenario"]).split("-") if len(t) > 2}),
        "covers": candidate.get("covers", ""),
        "covers_modules": candidate["covers_modules"],
        "promoted_from_run": (candidate.get("provenance") or {}).get("run", ""),
        "promoted_sha256": candidate.get("sha256", ""),
        "coverage_provenance": "runtime-observed",
    }
