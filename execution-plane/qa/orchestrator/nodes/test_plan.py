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

from orchestrator.context import criterion_ids, regression_candidates
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
the change if it's plausible they could break.

Every scenario's ac_ref MUST be one of the acceptance criterion ids listed in
the request. A scenario referencing an id that does not exist is rejected —
that reference is what ties the test back to the requirement it verifies."""

_VAGUE_PHRASES = [
    "should work",
    "works correctly",
    "functions properly",
    "behaves as expected",
    "looks good",
    "is correct",
]


def _is_testable(scenario: dict, known_criteria: set[str] | None = None) -> tuple[bool, str | None]:
    outcome = (scenario.get("expected_outcome") or "").strip().lower()
    if not outcome:
        return False, "no expected_outcome"
    if len(outcome) < 12:
        return False, "expected_outcome too vague/short"
    if any(p in outcome for p in _VAGUE_PHRASES):
        return False, f"expected_outcome uses a non-observable phrase: '{outcome}'"

    # A scenario that cannot say which criterion it verifies produces no
    # VERIFIED_BY edge, which means coverage can never be proved for it.
    if known_criteria:
        ac_ref = (scenario.get("ac_ref") or "").strip()
        if ac_ref not in known_criteria:
            return False, f"ac_ref {ac_ref!r} does not resolve to a known acceptance criterion"

    return True, None


def _evaluate(
    proposed: list[dict], known_criteria: set[str] | None = None
) -> tuple[list[dict], list[str]]:
    accepted: list[dict] = []
    reasons: list[str] = []
    for sc in proposed:
        ok, reason = _is_testable(sc, known_criteria)
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
    known = criterion_ids()
    # Regression scope comes from the dependency graph, not from the change
    # summary: a component the diff never touched can still be the one that
    # breaks, and only the graph knows that.
    scope = regression_candidates(state.get("changed_paths", []))

    base_user = (
        f"Change summary: {state['change_summary']}\n"
        f"Affected areas: {state['affected_areas']}\n"
        f"Acceptance criteria (use these exact ids for ac_ref):\n"
        + "\n".join(f"  {cid}: {meta['text']}" for cid, meta in known.items())
        + f"\n\nComponents impacted by this change, directly or through a dependency: "
        f"{scope['impacted_components']}\n"
        f"Existing scenarios covering those components, worth reusing as regression: "
        f"{scope['scenarios']}"
    )

    accepted: list[dict] = []
    reasons: list[str] = []
    attempt = 0

    while attempt < MAX_ATTEMPTS:
        attempt += 1
        user = base_user + (_revision_prompt(reasons) if reasons else "")
        plan = ask(SYSTEM, user, TestPlan)
        proposed = [s.model_dump() for s in plan.scenarios]

        accepted, reasons = _evaluate(proposed, set(known))
        if accepted and not reasons:
            return {
                **state,
                "test_plan": accepted,
                "regression_scope": scope,
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
        "regression_scope": scope,
        "test_plan_gate_passed": False,
        "test_plan_attempts": attempt,
        "test_plan_gate_reasons": [
            f"still not testable after {attempt} attempt(s):",
            *reasons,
        ],
    }
