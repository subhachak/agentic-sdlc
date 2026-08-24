"""Deterministic review of a proposed design.

The implementation phase may only touch what the design names, so this is
where "what may this change touch" becomes a fact rather than an assertion. A
design that names a module nobody has heard of, or a file that does not
exist, is refused here — before a human is asked to approve it, and long
before an agent is asked to implement it.

The impact set is derived rather than proposed: whatever the design names,
plus everything that depends on it, according to the graph. An architect can
be wrong about consequences; the dependency edges cannot.
"""

from __future__ import annotations

from dataclasses import dataclass, field

MAX_MODULES = 6
MAX_FILES = 15


@dataclass
class DesignReview:
    allowed: bool
    reasons: list[str] = field(default_factory=list)
    impact: dict[str, list[str]] = field(default_factory=dict)


def impact_set(
    files: list[str],
    file_dependents: dict[str, set[str]],
    path_to_module: dict[str, str] | None = None,
    depth: int = 1,
) -> dict[str, list[str]]:
    """What a change to these files can reach.

    Traversed at file level and rolled up to modules only for display.
    Rolling up first and traversing after is what gave every file in a
    directory the same blast radius — measured on one real repository, that
    was 13% of the codebase per change against 0.8% at file level.

    One hop by default. Deeper traversal over an import graph reaches most of
    a codebase, which is technically true and not a useful answer.
    """
    reached = set(files)
    frontier = set(files)
    for _ in range(max(0, depth)):
        nxt: set[str] = set()
        for path in frontier:
            nxt |= file_dependents.get(path, set())
        frontier = nxt - reached
        reached |= nxt

    modules = sorted(
        {path_to_module[p] for p in reached if p in (path_to_module or {})}
    ) if path_to_module else []
    return {"files": sorted(reached - set(files)), "modules": modules}


def review(
    proposal: dict,
    *,
    known_modules: dict[str, set[str]],
    file_dependents: dict[str, set[str]] | None = None,
    known_criteria: set[str] | None = None,
) -> DesignReview:
    reasons: list[str] = []
    modules = [c for c in proposal.get("modules", []) if c]
    files = [f for f in proposal.get("files", []) if f]

    path_to_module = {p: m for m, paths in known_modules.items() for p in paths}

    if not known_modules:
        # Nothing to check against. Say so rather than passing silently: a
        # design validated against an empty graph has not been validated.
        return DesignReview(
            True,
            ["the context graph is empty — the design was not validated against it"],
            impact_set(files, file_dependents or {}, path_to_module),
        )

    if not modules:
        reasons.append("the design names no modules")
    if not files:
        reasons.append("the design names no files, so the implementation phase would see nothing")

    if len(modules) > MAX_MODULES:
        reasons.append(f"{len(modules)} modules named, more than the {MAX_MODULES} allowed")
    if len(files) > MAX_FILES:
        reasons.append(f"{len(files)} files named, more than the {MAX_FILES} allowed")

    for module in modules:
        if module not in known_modules:
            reasons.append(f"unknown module {module!r}")

    owned = {path for c in modules for path in known_modules.get(c, set())}
    for path in files:
        if not any(path in paths for paths in known_modules.values()):
            reasons.append(f"unknown file {path!r}")
        elif path not in owned:
            reasons.append(f"{path} is not in any module the design named")

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

    return DesignReview(
        not reasons, reasons, impact_set(files, file_dependents or {}, path_to_module)
    )
