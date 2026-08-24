"""Deterministic review of a proposed design.

The implementation phase may only touch what the design names, so this is
where "what may this change touch" becomes a fact rather than an assertion. A
design that names a module nobody has heard of, or a file that does not
exist, is refused here — before a human is asked to approve it, and long
before an agent is asked to implement it.

The impact set is derived rather than proposed: whatever the design names,
plus everything that depends on it, according to the graph. An architect can
be wrong about consequences, and a derived answer is at least reproducible.

The edges can still be wrong. They are extracted statically, so they miss
coupling that only exists at runtime — an HTTP call between two services
produces no import edge at all — and they can resolve to the wrong file where
a package name is ambiguous. The index reports its own capture rate for
exactly this reason, and this module refuses to review against a graph too
poor to review against.
"""

from __future__ import annotations

from dataclasses import dataclass, field

MAX_MODULES = 6
MAX_FILES = 15

# Below this share of internal imports resolved, the graph does not know
# enough about the codebase for containment to mean anything: the modules a
# design names may be right and the impact set will still be missing edges
# nobody can see. Refusing is the only honest answer, and it is actionable —
# the seed says which specifiers it could not resolve.
MIN_CAPTURE_RATE = 0.80


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
    graph_quality: dict | None = None,
) -> DesignReview:
    reasons: list[str] = []
    modules = [c for c in proposal.get("modules", []) if c]
    files = [f for f in proposal.get("files", []) if f]

    path_to_module = {p: m for m, paths in known_modules.items() for p in paths}

    if not known_modules:
        # Nothing to check against, so nothing was checked. This used to
        # return allowed=True with a note, which meant the one condition
        # guaranteeing containment could not work was also the one condition
        # that let every design through.
        return DesignReview(
            False,
            [
                "the context graph holds no modules, so this design cannot be "
                "validated against the codebase — seed the graph from a repository "
                "before running a design phase"
            ],
            {"files": [], "modules": []},
        )

    if graph_quality is not None:
        capture = graph_quality.get("internal_capture_rate")
        if capture is not None and capture < MIN_CAPTURE_RATE:
            missed = graph_quality.get("most_missed") or []
            examples = ", ".join(spec for spec, _ in missed[:3])
            return DesignReview(
                False,
                [
                    f"the code index resolved only {capture:.1%} of imports that look "
                    f"internal, below the {MIN_CAPTURE_RATE:.0%} needed to derive an "
                    f"impact set that can be trusted"
                    + (f" — unresolved: {examples}" if examples else "")
                ],
                {"files": [], "modules": []},
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
