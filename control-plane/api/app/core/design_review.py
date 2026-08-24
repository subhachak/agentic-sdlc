"""Deterministic review of a proposed design.

The implementation phase may only touch what the design names, so this is
where "what may this change touch" becomes a fact rather than an assertion. A
design that names a component nobody has heard of, or a file that does not
exist, is refused here — before a human is asked to approve it, and long
before an agent is asked to implement it.

The impact set is derived rather than proposed: whatever the design names,
plus everything that depends on it, according to the graph. An architect can
be wrong about consequences; the dependency edges cannot.
"""

from __future__ import annotations

from dataclasses import dataclass, field

MAX_COMPONENTS = 6
MAX_FILES = 15


@dataclass
class DesignReview:
    allowed: bool
    reasons: list[str] = field(default_factory=list)
    impact: list[str] = field(default_factory=list)


def impact_set(
    components: list[str], dependents: dict[str, set[str]]
) -> list[str]:
    """The named components plus everything that depends on them.

    One hop. Deeper traversal over a directory-derived component graph
    produces impact sets that include most of the codebase, which is not a
    useful answer even when it is technically true.
    """
    reached = set(components)
    for component in components:
        reached |= dependents.get(component, set())
    return sorted(reached)


def review(
    proposal: dict,
    *,
    known_components: dict[str, set[str]],
    dependents: dict[str, set[str]] | None = None,
    known_criteria: set[str] | None = None,
) -> DesignReview:
    reasons: list[str] = []
    components = [c for c in proposal.get("components", []) if c]
    files = [f for f in proposal.get("files", []) if f]

    if not known_components:
        # Nothing to check against. Say so rather than passing silently: a
        # design validated against an empty graph has not been validated.
        return DesignReview(
            True,
            ["the context graph is empty — the design was not validated against it"],
            impact_set(components, dependents or {}),
        )

    if not components:
        reasons.append("the design names no components")
    if not files:
        reasons.append("the design names no files, so the implementation phase would see nothing")

    if len(components) > MAX_COMPONENTS:
        reasons.append(f"{len(components)} components named, more than the {MAX_COMPONENTS} allowed")
    if len(files) > MAX_FILES:
        reasons.append(f"{len(files)} files named, more than the {MAX_FILES} allowed")

    for component in components:
        if component not in known_components:
            reasons.append(f"unknown component {component!r}")

    owned = {path for c in components for path in known_components.get(c, set())}
    for path in files:
        if not any(path in paths for paths in known_components.values()):
            reasons.append(f"unknown file {path!r}")
        elif path not in owned:
            reasons.append(f"{path} is not in any component the design named")

    if known_criteria:
        addressed = set(proposal.get("criteria_addressed", []))
        excused = set(proposal.get("out_of_scope", []))
        for criterion in addressed | excused:
            if criterion not in known_criteria:
                reasons.append(f"unknown acceptance criterion {criterion!r}")
        missing = known_criteria - addressed - excused
        if missing:
            reasons.append(
                "criteria neither addressed nor declared out of scope: "
                + ", ".join(sorted(missing))
            )

    if not (proposal.get("rationale") or "").strip():
        reasons.append("no rationale — a human cannot approve a design that does not say why")

    return DesignReview(not reasons, reasons, impact_set(components, dependents or {}))
