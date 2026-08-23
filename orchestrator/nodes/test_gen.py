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
from pathlib import Path

from orchestrator.llm import ask_json
from orchestrator.state import PipelineState

REPO_ROOT = Path(__file__).resolve().parents[2]
LIBRARY_DIR = REPO_ROOT / "test-scripts"
# Inside sample-app/ on purpose: Node resolves imports by walking up from the
# spec file, so a spec at the repo root cannot see sample-app/node_modules and
# fails with "Cannot find module '@playwright/test'" before any test runs.
GENERATED_DIR = REPO_ROOT / "sample-app" / "generated-tests"

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

GEN_SYSTEM = """You are a Playwright test-generation agent for a Next.js app.
Given one test scenario, write a single Playwright test file in TypeScript.
Use page.getByTestId(...) selectors — the app exposes: nav-claims,
claims-table, claim-row (each row also has a data-status attribute),
status-filter (a <select> on /claims when present), empty-state.
Do not hard-code row counts that depend on how much data happens to be in
the store — derive expected counts from the /api/claims response instead.
Assert on the scenario's expected_outcome concretely (counts, visible text,
attribute values) — do not write vague assertions. Output JSON:
{"code": "import { test, expect } from '@playwright/test';\\n..."}"""


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


def run(state: PipelineState) -> PipelineState:
    _clear_generated_dir()
    manifest = json.loads((LIBRARY_DIR / "manifest.json").read_text())["scripts"]

    assignments = []
    for index, scenario in enumerate(state.get("test_plan", [])):
        scenario_id = scenario.get("id") or f"scenario-{index + 1}"
        dest = GENERATED_DIR / _spec_filename(scenario_id)
        existing = _select_existing(scenario, manifest)

        if existing:
            code = (LIBRARY_DIR / existing["file"]).read_text()
            mode, source_id = "selected", existing["id"]
        else:
            code = ask_json(GEN_SYSTEM, f"Scenario: {json.dumps(scenario)}")["code"]
            mode, source_id = "generated", None

        dest.write_text(f"// scenario: {scenario_id} ({mode})\n{code}")
        assignments.append(
            {
                "scenario_id": scenario_id,
                "mode": mode,
                "file_path": str(dest),
                "source_script_id": source_id,
            }
        )

    return {**state, "test_assignments": assignments}
