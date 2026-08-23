"""Phase 2 — Test plan: agent proposes scenarios, a deterministic gate
checks each one is actually testable before anything downstream trusts it.

This is the load-bearing gate of this design: no LLM in the gate itself. A
scenario either has an observable expected outcome or it gets rejected back
for revision. The revision is real — the rejection reasons are fed back to
the agent and it gets a bounded number of attempts to produce a plan that
passes, because halting the whole run over one vague sentence out of six is
not a useful pipeline.
"""
from __future__ import annotations

from orchestrator.llm import ask
from orchestrator.schemas import TestPlan
from orchestrator.state import PipelineState

MAX_ATTEMPTS = 3

SYSTEM = """You are a QA test-planning agent. Given a summary of what changed
in a PR and the affected areas, propose a set of test scenarios covering
the change: at least one happy path, one edge case, and one negative case
where applicable. Every scenario MUST have a concrete, observable
expected_outcome (something a test can assert on — a count, a visible
element, specific text) — never a vague statement like "should work
correctly". Also reuse relevant regression scenarios for areas adjacent to
the change if it's plausible they could break."""

_VAGUE_PHRASES = [
    "should work",
    "works correctly",
    "functions properly",
    "behaves as expected",
    "looks good",
    "is correct",
]


def _is_testable(scenario: dict) -> tuple[bool, str | None]:
    outcome = (scenario.get("expected_outcome") or "").strip().lower()
    if not outcome:
        return False, "no expected_outcome"
    if len(outcome) < 12:
        return False, "expected_outcome too vague/short"
    if any(p in outcome for p in _VAGUE_PHRASES):
        return False, f"expected_outcome uses a non-observable phrase: '{outcome}'"
    return True, None


def _evaluate(proposed: list[dict]) -> tuple[list[dict], list[str]]:
    accepted: list[dict] = []
    reasons: list[str] = []
    for sc in proposed:
        ok, reason = _is_testable(sc)
        if ok:
            accepted.append(sc)
        else:
            reasons.append(f"{sc.get('id', '?')}: rejected — {reason}")
    return accepted, reasons


def _revision_prompt(reasons: list[str]) -> str:
    return (
        "\n\nYour previous proposal was rejected by the testability gate:\n"
        + "\n".join(f"- {r}" for r in reasons)
        + "\n\nRewrite the full set of scenarios. Every expected_outcome must name "
        "something a Playwright assertion can observe: an exact row count, a "
        "data-status attribute value, a specific visible string, an HTTP status. "
        "Do not restate the same wording."
    )


def run(state: PipelineState) -> PipelineState:
    base_user = (
        f"Change summary: {state['change_summary']}\n"
        f"Affected areas: {state['affected_areas']}\n"
        f"Feature context: {state.get('features_context', {})}"
    )

    accepted: list[dict] = []
    reasons: list[str] = []
    attempt = 0

    while attempt < MAX_ATTEMPTS:
        attempt += 1
        user = base_user + (_revision_prompt(reasons) if reasons else "")
        plan = ask(SYSTEM, user, TestPlan)
        proposed = [s.model_dump() for s in plan.scenarios]

        accepted, reasons = _evaluate(proposed)
        if accepted and not reasons:
            return {
                **state,
                "test_plan": accepted,
                "test_plan_gate_passed": True,
                "test_plan_attempts": attempt,
                "test_plan_gate_reasons": [
                    f"all {len(accepted)} proposed scenarios passed the testability gate"
                    + (f" on attempt {attempt}" if attempt > 1 else "")
                ],
            }

        if not proposed:
            reasons = ["the agent proposed no scenarios at all"]

    return {
        **state,
        "test_plan": accepted,
        "test_plan_gate_passed": False,
        "test_plan_attempts": attempt,
        "test_plan_gate_reasons": [
            f"still not testable after {attempt} attempt(s):",
            *reasons,
        ],
    }
