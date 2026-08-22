"""Phase 2 — Test plan: agent proposes scenarios, a deterministic gate
checks each one is actually testable before anything downstream trusts it.

This is the load-bearing gate of this design: no LLM in the
gate itself. A scenario either has an observable expected outcome or it
gets rejected back for revision — it never silently passes through vague.
"""
from __future__ import annotations

from orchestrator.llm import ask_json
from orchestrator.state import PipelineState

SYSTEM = """You are a QA test-planning agent. Given a summary of what changed
in a PR and the affected areas, propose a set of test scenarios covering
the change: at least one happy path, one edge case, and one negative case
where applicable. Every scenario MUST have a concrete, observable
expected_outcome (something a test can assert on — a count, a visible
element, specific text) — never a vague statement like "should work
correctly". Also reuse relevant regression scenarios for areas adjacent to
the change if it's plausible they could break.

Output JSON:
{
  "scenarios": [
    {
      "id": "short-kebab-id",
      "title": "...",
      "type": "functional|regression|edge-case|negative",
      "target_route": "/claims",
      "expected_outcome": "concrete, assertable outcome",
      "priority": "P1|P2|P3",
      "confidence": "high|medium|low",
      "ac_ref": "which acceptance criterion or change this covers"
    }
  ]
}"""

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


def run(state: PipelineState) -> PipelineState:
    user = (
        f"Change summary: {state['change_summary']}\n"
        f"Affected areas: {state['affected_areas']}\n"
        f"Feature context: {state.get('features_context', {})}"
    )
    result = ask_json(SYSTEM, user)
    proposed = result["scenarios"]

    accepted: list[dict] = []
    reasons: list[str] = []
    for sc in proposed:
        ok, reason = _is_testable(sc)
        if ok:
            accepted.append(sc)
        else:
            reasons.append(f"{sc.get('id', '?')}: rejected — {reason}")

    gate_passed = len(accepted) > 0 and len(reasons) == 0

    return {
        **state,
        "test_plan": accepted,
        "test_plan_gate_passed": gate_passed,
        "test_plan_gate_reasons": reasons or ["all proposed scenarios passed the testability gate"],
    }
