"""Phase 4 — For each planned scenario: select an existing script from the
library, or generate a new one. Selection is deterministic scoring against
the manifest; generation is the only LLM call in this node, and only runs
for scenarios nothing in the library covers.

Every scenario gets its own spec file named after the scenario id, whether
it was selected or generated. That keeps the plan -> file -> test-result
chain one-to-one, which is what lets nodes/gate.py detect a scenario that
silently went missing between plan and run.
"""
from __future__ import annotations

import json
import re
import shutil

from orchestrator.adapters.inline_test_author import InlineTestAuthor
from orchestrator.context import api_contract, ui_contract
from orchestrator.ports import TestAuthor
from orchestrator.state import PipelineState
from orchestrator.paths import GENERATED_DIR, LIBRARY_DIR
from orchestrator.validate import validate_spec

# A library script is reused only if it demonstrably covers the same ground
# as the scenario. Matching on bare substrings does not work here: the tag
# "claims" is a substring of the route "/claims", so every scenario matched
# the first entry in the manifest and the generation path never ran.
_MATCH_THRESHOLD = 0.6

_STOPWORDS = {
    "a", "all", "an", "and", "any", "are", "as", "at", "be", "by", "each",
    "every", "for", "from", "has", "have", "in", "is", "it", "its", "of",
    "on", "only", "or", "that", "the", "their", "then", "there", "this",
    "to", "when", "which", "with", "shows", "show",
}



def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", (text or "").lower()) if t not in _STOPWORDS}


def _scenario_tokens(scenario: dict) -> set[str]:
    return _tokens(
        f"{scenario.get('title', '')} "
        f"{scenario.get('expected_outcome', '')} "
        f"{scenario.get('ac_ref', '')}"
    )


def _score(scenario: dict, entry: dict) -> float:
    """Fraction of the library entry's 'covers' vocabulary that the scenario
    actually mentions. 1.0 means the scenario talks about everything the
    script checks; 0.0 means they have nothing in common."""
    covers = _tokens(entry.get("covers", ""))
    if not covers:
        return 0.0
    return len(covers & _scenario_tokens(scenario)) / len(covers)


def _select_existing(scenario: dict, manifest: list[dict]) -> dict | None:
    scenario_tokens = _scenario_tokens(scenario)
    route = (scenario.get("target_route") or "").strip().lower()

    best, best_score = None, 0.0
    for entry in manifest:
        entry_route = (entry.get("route") or "").strip().lower()
        if entry_route and route and entry_route != route:
            continue
        # Tags are matched as whole tokens, never as substrings.
        if not (set(entry.get("tags", [])) & scenario_tokens):
            continue
        score = _score(scenario, entry)
        if score > best_score:
            best, best_score = entry, score

    return best if best_score >= _MATCH_THRESHOLD else None


def _spec_filename(scenario_id: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (scenario_id or "").lower()).strip("-")
    return f"{slug or 'scenario'}.spec.ts"


def _clear_generated_dir() -> None:
    """Specs left over from a previous run are still inside Playwright's
    testDir, so they would execute and be counted by the gate."""
    if GENERATED_DIR.exists():
        shutil.rmtree(GENERATED_DIR)
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)


def _install_required_regressions(
    required_ids: list[str], manifest: list[dict], assignments: list[dict]
) -> tuple[list[dict], list[str]]:
    """Put every required regression script into the run, by construction.

    Not asked of the agent. The blast radius used to arrive as a sentence in
    the planning prompt — "worth reusing as regression" — which a model was
    free to ignore, and the plan gate only checked that whatever it did
    propose was testable. A required script is now placed into the run here,
    where nothing can decline it.

    A script already selected for one of the agent's scenarios counts: it is
    the same file and the same assertions, so running it twice would prove
    nothing and cost a browser.
    """
    already = {a.get("source_script_id") for a in assignments}
    by_id = {entry["id"]: entry for entry in manifest}

    added: list[dict] = []
    missing: list[str] = []
    for script_id in required_ids:
        entry = by_id.get(script_id)
        if entry is None:
            missing.append(script_id)
            continue
        if script_id in already:
            continue
        dest = GENERATED_DIR / _spec_filename(f"regression-{script_id}")
        dest.write_text(
            f"// required regression: {script_id} (blast radius)\n"
            + (LIBRARY_DIR / entry["file"]).read_text()
        )
        added.append(
            {
                "scenario_id": f"regression:{script_id}",
                "mode": "required-regression",
                "file_path": str(dest),
                "source_script_id": script_id,
            }
        )
    return added, missing


def run(state: PipelineState, author: TestAuthor | None = None) -> PipelineState:
    # Defaults to this platform's own agent. Whoever writes the spec, it is
    # refused by validate_spec before it can execute — the sandbox was built
    # for agent-authored code and does not care which agent.
    author = author or InlineTestAuthor()
    _clear_generated_dir()
    manifest = json.loads((LIBRARY_DIR / "manifest.json").read_text())["scripts"]

    assignments = []
    rejections: list[str] = []
    for index, scenario in enumerate(state.get("test_plan", [])):
        scenario_id = scenario.get("id") or f"scenario-{index + 1}"
        dest = GENERATED_DIR / _spec_filename(scenario_id)
        existing = _select_existing(scenario, manifest)

        if existing:
            code = (LIBRARY_DIR / existing["file"]).read_text()
            mode, source_id = "selected", existing["id"]
        else:
            written = author.write_spec(
                {
                    "scenario": scenario,
                    "ui_contract": ui_contract(),
                    "api_contract": api_contract(),
                }
            )
            if written.get("state") == "pending":
                # A dispatched author has not produced a spec yet. Recorded
                # as a rejection rather than silently skipped: a scenario
                # with no assignment fails the plan-vs-assignment count in
                # the gate, which is the correct outcome until the resume
                # path exists.
                rejections.append(
                    f"{scenario_id}: spec authoring was dispatched to "
                    f"{written.get('provider')} and has not returned"
                )
                continue
            code = written.get("spec") or ""
            mode, source_id = "generated", None

        # Fail closed. A spec that trips the validator is never written, so it
        # cannot execute; the scenario then has no assignment and nodes/gate.py
        # fails the run on the plan-vs-assignment count.
        violations = validate_spec(code)
        if violations:
            rejections.append(f"{scenario_id}: refused {mode} spec — {'; '.join(violations)}")
            continue

        dest.write_text(f"// scenario: {scenario_id} ({mode})\n{code}")
        assignments.append(
            {
                "scenario_id": scenario_id,
                "mode": mode,
                "file_path": str(dest),
                "source_script_id": source_id,
            }
        )

    scope = state.get("regression_scope") or {}
    required_ids = list(scope.get("required_scripts") or [])
    installed, missing = _install_required_regressions(required_ids, manifest, assignments)
    assignments.extend(installed)
    # A required script the library cannot produce is a broken graph, not a
    # test failure. It surfaces here so the gate can refuse rather than
    # reporting a clean run over a regression set that never existed.
    rejections.extend(
        f"required regression script {script_id!r} is not in the library" for script_id in missing
    )

    return {
        **state,
        "test_assignments": assignments,
        "generation_rejections": rejections,
        "required_assignments": [a["source_script_id"] for a in assignments
                                 if a.get("source_script_id") in set(required_ids)],
    }
