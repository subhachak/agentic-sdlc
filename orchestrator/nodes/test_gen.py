"""Phase 4 — For each planned scenario: select an existing script from the
library, or generate a new one. Selection is deterministic keyword
matching against the manifest; generation is the only LLM call in this
node, and only runs for scenarios nothing in the library covers.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from orchestrator.llm import ask_json
from orchestrator.state import PipelineState

REPO_ROOT = Path(__file__).resolve().parents[2]
LIBRARY_DIR = REPO_ROOT / "test-scripts"
GENERATED_DIR = REPO_ROOT / "generated-tests"

GEN_SYSTEM = """You are a Playwright test-generation agent for a Next.js app.
Given one test scenario, write a single Playwright test file in TypeScript.
Use page.getByTestId(...) selectors — the app exposes: nav-claims,
claims-table, claim-row (each row also has a data-status attribute),
status-filter (a <select> on /claims when present). Assert on the scenario's
expected_outcome concretely (counts, visible text, attribute values) — do
not write vague assertions. Output JSON:
{"file_name": "kebab-scenario-id.spec.ts", "code": "import { test, expect } from '@playwright/test';\\n..."}"""


def _select_existing(scenario: dict, manifest: list[dict]) -> dict | None:
    haystack = f"{scenario.get('title','')} {scenario.get('target_route','')}".lower()
    for entry in manifest:
        if any(tag in haystack for tag in entry["tags"]):
            return entry
        if entry["id"].replace("-", " ") in haystack:
            return entry
    return None


def run(state: PipelineState) -> PipelineState:
    GENERATED_DIR.mkdir(exist_ok=True)
    manifest = json.loads((LIBRARY_DIR / "manifest.json").read_text())["scripts"]

    assignments = []
    for scenario in state.get("test_plan", []):
        existing = _select_existing(scenario, manifest)
        if existing:
            src = LIBRARY_DIR / existing["file"]
            dest = GENERATED_DIR / existing["file"]
            dest.write_text(src.read_text())
            assignments.append(
                {
                    "scenario_id": scenario["id"],
                    "mode": "selected",
                    "file_path": str(dest),
                    "source_script_id": existing["id"],
                }
            )
            continue

        result = ask_json(GEN_SYSTEM, f"Scenario: {json.dumps(scenario)}")
        file_name = re.sub(r"[^a-z0-9\-]", "-", result["file_name"].lower())
        if not file_name.endswith(".spec.ts"):
            file_name = file_name.rsplit(".", 1)[0] + ".spec.ts"
        dest = GENERATED_DIR / file_name
        dest.write_text(result["code"])
        assignments.append(
            {
                "scenario_id": scenario["id"],
                "mode": "generated",
                "file_path": str(dest),
                "source_script_id": None,
            }
        )

    return {**state, "test_assignments": assignments}
