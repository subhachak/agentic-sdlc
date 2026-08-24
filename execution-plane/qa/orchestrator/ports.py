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

from typing import Any, Protocol


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


class TestAuthor(Protocol):
    """Proposes scenarios, and writes the specs nothing in the library covers."""

    def propose_plan(self, request: PlanRequest) -> list[dict[str, Any]]: ...
    """Scenarios, as dicts matching the TestPlan schema's shape. Returning
    none is allowed and means the required regressions are the whole run."""

    def write_spec(self, request: SpecRequest) -> str: ...
    """One Playwright spec, as TypeScript source. Checked by validate_spec
    before it is written anywhere, whoever produced it."""
