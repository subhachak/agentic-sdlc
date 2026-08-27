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

from orchestrator import data_store
from orchestrator.adapters.inline_test_author import InlineTestAuthor
from orchestrator.context import criterion_ids, regression_candidates
from orchestrator.ports_execution import ANY_FIELD
from orchestrator.ports import TestAuthor
from orchestrator.state import PipelineState

MAX_ATTEMPTS = 3


_VAGUE_PHRASES = [
    "should work",
    "works correctly",
    "functions properly",
    "behaves as expected",
    "looks good",
    "is correct",
]


def _data_is_satisfiable(
    scenario: dict, shape: dict[str, set[str]] | None
) -> tuple[bool, str | None]:
    """Reject a scenario whose data needs nothing can provide.

    Caught here rather than at seeding time so the agent gets the chance to
    revise, and so an unsatisfiable plan never reaches a browser.
    """
    if not shape:
        return True, None
    for requirement in scenario.get("required_data") or []:
        entity = requirement.get("entity", "")
        field = requirement.get("field", "")
        if entity not in shape:
            return False, f"required_data names unknown entity {entity!r}"
        fields = shape[entity]
        # A provider that knows its entities but not their fields says so
        # with ANY_FIELD. Checking membership literally would reject every
        # field name, which is refusing a plan for want of information the
        # provider never claimed to have.
        if ANY_FIELD in fields:
            continue
        if field not in fields:
            return False, f"required_data names unknown field {entity}.{field}"
    return True, None


def _is_testable(
    scenario: dict,
    known_criteria: set[str] | None = None,
    shape: dict[str, set[str]] | None = None,
) -> tuple[bool, str | None]:
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

    return _data_is_satisfiable(scenario, shape)


def _evaluate(
    proposed: list[dict],
    known_criteria: set[str] | None = None,
    shape: dict[str, set[str]] | None = None,
) -> tuple[list[dict], list[str]]:
    accepted: list[dict] = []
    reasons: list[str] = []
    for sc in proposed:
        ok, reason = _is_testable(sc, known_criteria, shape)
        if ok:
            accepted.append(sc)
        else:
            reasons.append(f"{sc.get('id', '?')}: rejected — {reason}")
    return accepted, reasons


def run(state: PipelineState, author: TestAuthor | None = None) -> PipelineState:
    # Defaults to this platform's own agent. A client substitutes one here
    # rather than forking the phase, and the gate below does not move.
    author = author or InlineTestAuthor()

    known = criterion_ids()
    # From the configured provider, not the JSON store directly — an
    # application that mocks at the network boundary has no store, and
    # reading one would gate its plans against an empty shape.
    from orchestrator.nodes.test_run import build_test_data_provider

    shape = build_test_data_provider().shape()
    # Regression scope comes from the dependency graph, not from the change
    # summary: a module the diff never touched can still be the one that
    # breaks, and only the graph knows that.
    #
    # What the scope names as `required_scripts` is not a suggestion to the
    # agent. Those scripts are installed into the run by test_gen and enforced
    # by the gate, so the request tells the agent to skip them and spend its
    # scenarios on the areas nothing covers.
    scope = regression_candidates(
        state.get("changed_paths", []), head_sha=state.get("head_sha") or ""
    )

    request = {
        "change_summary": state["change_summary"],
        "affected_areas": state["affected_areas"],
        "criteria": known,
        "data_shape": {entity: sorted(fields) for entity, fields in (shape or {}).items()},
        "impacted_modules": scope["impacted_components"],
        "required_scripts": scope["required_scripts"],
        "uncovered_modules": scope["uncovered_components"],
        "graph_warnings": scope.get("graph_warnings") or [],
    }

    accepted: list[dict] = []
    reasons: list[str] = []
    attempt = 0

    while attempt < MAX_ATTEMPTS:
        attempt += 1
        # Whoever authors it, the gate is the same. An agent supplied by a
        # client proposes; deterministic code decides.
        outcome = author.propose_plan({**request, "rejected_reasons": reasons})
        if outcome.get("state") == "pending":
            # A dispatched author parks the run, the same way QA parks for
            # CI. Not reachable with the shipped author, which is
            # synchronous — branching on the state rather than on which
            # author is configured is what stops this node growing an arm
            # per client.
            return {
                **state,
                "status": "awaiting_test_author",
                "test_author_dispatch": {
                    "provider": outcome.get("provider"),
                    "handle": outcome.get("handle"),
                },
            }
        proposed = outcome.get("plan") or []

        accepted, reasons = _evaluate(proposed, set(known), shape)
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
