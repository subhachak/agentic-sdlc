"""Ports the QA plane offers a client.

The default implementations are local and stay that way: an agent whose
behaviour is known here is the right default, and a client's is a
substitution rather than an upgrade. What the port buys is that substituting
one is configuration rather than a fork of the pipeline.

The deterministic half does not move. Whatever authors a test plan, its
scenarios still have to pass the testability gate — an observable outcome, an
`ac_ref` that resolves, data the store can provide. Whatever writes a spec,
it still has to pass `validate_spec` before it is allowed to execute. And the
regression scripts the blast radius requires are still installed by code
rather than requested from an agent, because an agent that can decline to run
them is not a control.

A client's agent is reviewed slightly more suspiciously than the shipped one,
for the obvious reason: it is the one that can change without anyone here
knowing.
"""

from __future__ import annotations

from typing import Any, Literal, Protocol

# Bumped when the shape crossing this boundary changes. These requests are
# plain dicts on purpose — the QA plane hands them to whatever the client
# runs, and a shared schema would need versioning in two places at once. But
# "no schema" and "no contract" are different things, and this is the second
# one: a client agent can refuse a version it does not understand instead of
# misreading a field that moved.
AUTHOR_CONTRACT_VERSION = 1


class PlanRequest(dict):
    """What an agent needs to propose scenarios.

    A plain dict rather than a model: the execution plane hands this across a
    process boundary to whatever the client runs, and a schema shared across
    that boundary would have to be versioned in two places at once — the same
    reason the assertions the QA plane emits are plain dicts.

    Keys: change_summary, affected_areas, criteria, data_shape,
    impacted_modules, required_scripts, uncovered_modules, graph_warnings.
    """


class SpecRequest(dict):
    """What an agent needs to write one Playwright spec.

    Keys: scenario, ui_contract, api_contract.
    """


class AuthorOutcome(dict):
    """Either an answer or a receipt.

    The shipped author is in-process and answers in seconds. A client's test
    agent is the same shape as their coding agent: dispatched, working for
    an hour, answering into somewhere else. The port could express only the
    first, so the second would have had to block the pipeline or lie about
    finishing — and every other long-running seam in this platform is a
    dispatch with a receipt.

    Keys: state ("ready" | "pending"), plan | spec, provider, handle.
    """


class TestAuthor(Protocol):
    """Proposes scenarios, and writes the specs nothing in the library covers.

    Whatever authors a plan, its scenarios still pass the testability gate —
    an observable outcome, an ac_ref that resolves, data the provider can
    actually supply. Whatever writes a spec, it still passes validate_spec.
    And the regressions the blast radius requires are installed by code, not
    requested, because an agent that can decline to run them is not a
    control.
    """

    contract_version: int

    def capabilities(self) -> dict[str, Any]: ...
    """What this author can and cannot do.

    Read before it is asked, so the pipeline degrades deliberately rather
    than discovering a gap in a returned value. An author that cannot write
    specs for a given runner says so and the library-only path is taken;
    one that silently returned nothing would look identical to a change
    needing no new tests.

    Keys: runners (list), can_author_specs (bool), dispatched (bool),
    max_scenarios (int).
    """

    def propose_plan(self, request: PlanRequest) -> AuthorOutcome: ...
    """Scenarios, as dicts matching the TestPlan schema's shape.

    An empty plan is allowed and means the required regressions are the
    whole run — which is a real answer for a change fully covered by the
    library."""

    def write_spec(self, request: SpecRequest) -> AuthorOutcome: ...
    """One spec, as source. Checked by validate_spec before it is written
    anywhere, whoever produced it."""

    def read_result(self, payload: dict[str, Any]) -> AuthorOutcome: ...
    """Interpret a finished dispatch.

    Separate because the two run in different processes: a dispatched author
    outlives the request that started it, and is resumed with nothing but
    the payload. In-process authors never have this called."""


def ready(**payload: Any) -> AuthorOutcome:
    return AuthorOutcome(state="ready", **payload)


def pending(provider: str, handle: str) -> AuthorOutcome:
    return AuthorOutcome(state="pending", provider=provider, handle=handle)
