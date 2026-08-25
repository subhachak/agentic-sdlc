"""The default test author: this platform's own agent, calling a model.

Holds the prompts that were previously inline in the two nodes. Moving them
here changes no behaviour — the same system prompts, the same schemas, the
same revision loop driven by the same deterministic gate — and makes the
substitution point one class rather than two call sites buried in phases.
"""

from __future__ import annotations

import json
from typing import Any

from orchestrator.llm import ask
from orchestrator.ports import PlanRequest, SpecRequest
from orchestrator.prompts import GEN_SYSTEM, PLAN_SYSTEM
from orchestrator.schemas import GeneratedSpec, TestPlan


class InlineTestAuthor:
    def propose_plan(self, request: PlanRequest) -> list[dict[str, Any]]:
        criteria = request.get("criteria") or {}
        criteria_text = "\n".join(
            f"  {cid}: {meta['text']}" for cid, meta in criteria.items()
        )
        user = (
            f"Change summary: {request.get('change_summary', '')}\n"
            f"Affected areas: {request.get('affected_areas', '')}\n"
            f"Acceptance criteria (use these exact ids for ac_ref):\n{criteria_text}\n\n"
            f"Modules impacted by this change, directly or through a dependency: "
            f"{request.get('impacted_modules', [])}\n"
            f"Regression scripts already being run for those modules (do not re-plan "
            f"these): {request.get('required_scripts', [])}\n"
            f"Impacted modules with NO regression coverage — nothing else in this run "
            f"will exercise them: {request.get('uncovered_modules', [])}"
        )
        warnings = request.get("graph_warnings") or []
        if warnings:
            user += "\nThe dependency graph behind that scope is qualified: " + "; ".join(warnings)
        if request.get("rejected_reasons"):
            user += _revision_prompt(request["rejected_reasons"])

        plan = ask(PLAN_SYSTEM, user, TestPlan)
        return [scenario.model_dump() for scenario in plan.scenarios]

    def write_spec(self, request: SpecRequest) -> str:
        return ask(
            GEN_SYSTEM,
            f"UI contract, by route:\n{request.get('ui_contract', '')}\n\n"
            f"API contract:\n{request.get('api_contract', '')}\n\n"
            f"Scenario: {json.dumps(request.get('scenario', {}))}",
            GeneratedSpec,
        ).code


def _revision_prompt(reasons: list[str]) -> str:
    return (
        "\n\nYour previous proposal was rejected by the testability gate:\n"
        + "\n".join(f"- {r}" for r in reasons)
        + "\n\nRewrite the full set of scenarios. Every expected_outcome must name "
        "something a Playwright assertion can observe: an exact row count, a "
        "data-status attribute value, a specific visible string, an HTTP status. "
        "Do not restate the same wording."
    )
