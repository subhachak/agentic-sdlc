"""One impact calculation, with semantics attached to the relationship.

There were three, and they disagreed. The design gate traversed files two
hops and rolled up for display; the graph's blast_radius traversed modules
two hops over DEPENDS_ON; the execution plane traversed modules one hop over
the exported rollup. On one real file — apps/web/app/lib/format.ts — the
design gate reported a change reaching `app/app` that QA never required a
test for, while QA required `app/blog` the design gate never named. A change
could pass a containment check and be tested against a different set.

Three implementations is the symptom. The cause is that traversal was
written at each call site, so what an edge *means* lived in whoever
happened to be walking it. Here each relationship declares its own
semantics, and one function walks them.

Deliberately pure: no I/O, no session, no settings. It takes a graph
projection and a policy, and returns an assessment that carries its own
provenance — the same inputs give the same answer, and the answer can say
why.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

# Bumped when traversal changes in a way that would move an answer. Carried
# on the assessment so a stored decision can be told apart from one this
# version would make now.
ENGINE_VERSION = "1.0.0"

# How sure we are allowed to be about a relationship, by how it was found.
# An LLM-proposed edge must never be indistinguishable from one the parser
# read out of an import statement — in an agentic platform that is the
# difference between evidence and a guess with good posture.
TruthClass = Literal["authoritative", "derived", "observed", "inferred"]

CONFIDENCE: dict[TruthClass, float] = {
    "authoritative": 1.0,
    "derived": 0.9,
    "observed": 0.8,
    "inferred": 0.5,
}


@dataclass(frozen=True)
class Semantics:
    """What one relationship means for impact.

    A generic breadth-first walk treats every edge as "related somehow",
    which is how a deployment edge and an import edge end up producing the
    same test obligation.
    """

    edge: str
    truth: TruthClass
    # Impact flows against the edge: if A imports B and B changes, A is
    # affected. "to_source" means the source of the edge is what a change to
    # the target reaches.
    direction: Literal["to_source", "to_target"] = "to_source"
    # Which kinds of change actually propagate. An import edge does not carry
    # a formatting change the way it carries a signature change — the
    # prototype cannot tell those apart yet, so `any` is honest and the field
    # is where that knowledge lands when it exists.
    propagates_on: frozenset[str] = frozenset({"any"})
    # Whether reaching something across this edge obliges a test. A service
    # deployed alongside another carries operational risk without carrying
    # code-test scope.
    test_obligation: bool = True
    # Beyond this many hops the relationship stops being evidence. None means
    # the policy's limit applies.
    max_depth: int | None = None
    note: str = ""


# The registry. A client's own edge type is not gated on until it appears
# here with semantics — a namespaced `x_depends_on_policy` edge that nothing
# knows how to propagate is stored and displayed, never silently traversed
# as though its meaning were understood.
SEMANTICS: dict[str, Semantics] = {
    "IMPORTS": Semantics(
        edge="IMPORTS",
        truth="derived",
        direction="to_source",
        note="the compiler's own answer, read from the import statement",
    ),
    "CALLS_ENDPOINT": Semantics(
        edge="CALLS_ENDPOINT",
        truth="derived",
        direction="to_source",
        note="a fetch literal matched to a declared route; real coupling with no import",
    ),
    "DEPENDS_ON": Semantics(
        edge="DEPENDS_ON",
        truth="derived",
        direction="to_source",
        note="the module-level rollup of the file edges above",
    ),
    "DEPLOYED_TO": Semantics(
        edge="DEPLOYED_TO",
        truth="authoritative",
        direction="to_target",
        test_obligation=False,
        note="operational blast radius, not code-test scope",
    ),
}


@dataclass(frozen=True)
class Policy:
    """The client's answer to "how far is too far".

    Versioned because an assessment that cannot name the policy behind it
    cannot be reproduced, and "why was this test selected" is the question
    the whole system exists to answer.
    """

    version: str = "default/1"
    # Measured, not chosen. See design_review.DEFAULT_DEPTH for the table.
    max_depth: int = 2
    # Below this an edge is reported but does not create an obligation.
    min_confidence: float = 0.4
    edges: frozenset[str] = frozenset({"IMPORTS", "CALLS_ENDPOINT"})
    include_tests: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "max_depth": self.max_depth,
            "min_confidence": self.min_confidence,
            "edges": sorted(self.edges),
            "include_tests": self.include_tests,
        }


@dataclass(frozen=True)
class Edge:
    """One relationship, as the engine consumes it."""

    type: str
    source: str
    target: str
    # Where it came from, carried through to the explanation.
    provenance: str = ""


@dataclass(frozen=True)
class ChangeSet:
    """What changed, and how."""

    paths: tuple[str, ...]
    kind: str = "any"

    def as_dict(self) -> dict[str, Any]:
        return {"paths": list(self.paths), "kind": self.kind}


@dataclass(frozen=True)
class Path:
    """Why one entity is in the assessment.

    An impact set without paths is an assertion. With them it is an argument
    someone can check, and disagree with.
    """

    entity: str
    hops: tuple[tuple[str, str], ...]  # (edge type, entity reached)
    confidence: float
    depth: int
    obliges_test: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "entity": self.entity,
            "via": [{"edge": e, "entity": n} for e, n in self.hops],
            "confidence": round(self.confidence, 3),
            "depth": self.depth,
            "obliges_test": self.obliges_test,
        }


@dataclass
class Assessment:
    """A decision artifact. Immutable in intent, explainable by construction."""

    changed: list[str]
    direct: list[str]
    transitive: list[str]
    paths: list[Path]
    unmapped: list[str]
    test_obligations: list[str]
    blind_spots: list[str]
    policy: Policy
    snapshot: dict[str, Any] = field(default_factory=dict)
    engine_version: str = ENGINE_VERSION

    @property
    def affected(self) -> list[str]:
        return sorted(set(self.direct) | set(self.transitive))

    def as_dict(self) -> dict[str, Any]:
        return {
            "engine_version": self.engine_version,
            "policy": self.policy.as_dict(),
            "snapshot": self.snapshot,
            "changed": self.changed,
            "direct": self.direct,
            "transitive": self.transitive,
            "affected": self.affected,
            "paths": [p.as_dict() for p in self.paths],
            "unmapped": self.unmapped,
            "test_obligations": self.test_obligations,
            "blind_spots": self.blind_spots,
        }


def assess(
    change: ChangeSet,
    edges: list[Edge],
    *,
    policy: Policy | None = None,
    known: set[str] | None = None,
    snapshot: dict[str, Any] | None = None,
) -> Assessment:
    """What this change reaches, why, and what that obliges.

    One traversal, driven by each relationship's declared semantics rather
    than by whoever wrote the call site.
    """
    policy = policy or Policy()
    known = known if known is not None else set()

    # Index by the end a change propagates *from*, so direction is applied
    # once here rather than being implied by how a caller happens to index.
    outgoing: dict[str, list[tuple[str, str]]] = {}
    for edge in edges:
        rules = SEMANTICS.get(edge.type)
        if rules is None or edge.type not in policy.edges:
            continue
        if "any" not in rules.propagates_on and change.kind not in rules.propagates_on:
            continue
        frm, to = (
            (edge.target, edge.source)
            if rules.direction == "to_source"
            else (edge.source, edge.target)
        )
        outgoing.setdefault(frm, []).append((edge.type, to))

    changed = sorted(set(change.paths))
    # A changed file no module owns cannot be reasoned about at all, and
    # saying so is the difference between "nothing is affected" and "we
    # cannot tell".
    unmapped = sorted(p for p in changed if known and p not in known)

    best: dict[str, Path] = {}
    frontier: list[tuple[str, tuple[tuple[str, str], ...], float]] = [
        (p, (), 1.0) for p in changed
    ]
    seen = set(changed)

    for depth in range(1, policy.max_depth + 1):
        nxt: list[tuple[str, tuple[tuple[str, str], ...], float]] = []
        for node, hops, confidence in frontier:
            for edge_type, reached in outgoing.get(node, []):
                rules = SEMANTICS[edge_type]
                if rules.max_depth is not None and depth > rules.max_depth:
                    continue
                # Confidence compounds: two derived hops is a weaker claim
                # than one, and a path that never says so overstates itself
                # the further it goes.
                score = confidence * CONFIDENCE[rules.truth]
                path = Path(
                    entity=reached,
                    hops=hops + ((edge_type, reached),),
                    confidence=score,
                    depth=depth,
                    obliges_test=rules.test_obligation and score >= policy.min_confidence,
                )
                # The strongest reason wins. Reporting the first path found
                # makes the answer depend on edge ordering.
                if reached not in best or score > best[reached].confidence:
                    best[reached] = path
                if reached not in seen:
                    seen.add(reached)
                    nxt.append((reached, path.hops, score))
        frontier = nxt
        if not frontier:
            break

    for p in changed:
        best.pop(p, None)

    direct = sorted(e for e, p in best.items() if p.depth == 1)
    transitive = sorted(e for e, p in best.items() if p.depth > 1)
    obligations = sorted(e for e, p in best.items() if p.obliges_test)

    # What this cannot see. Named rather than omitted: an impact set that
    # quietly excludes what it could not resolve reads as completeness.
    blind: list[str] = []
    if unmapped:
        blind.append(
            f"{len(unmapped)} changed file(s) belong to no indexed module, so nothing "
            f"downstream of them was traversed"
        )
    untyped = sorted({e.type for e in edges} - set(SEMANTICS))
    if untyped:
        blind.append(
            "relationships present in the graph with no declared impact semantics, so "
            "not traversed: " + ", ".join(untyped)
        )
    ignored = sorted(set(SEMANTICS) - set(policy.edges))
    if ignored:
        blind.append("excluded by policy: " + ", ".join(ignored))

    return Assessment(
        changed=changed,
        direct=direct,
        transitive=transitive,
        paths=sorted(best.values(), key=lambda p: (-p.confidence, p.entity)),
        unmapped=unmapped,
        test_obligations=obligations,
        blind_spots=blind,
        policy=policy,
        snapshot=snapshot or {},
    )


def roll_up(entities: list[str], path_to_module: dict[str, str]) -> list[str]:
    """File-level answers, grouped for display only.

    Rolling up *before* traversing is what gave every file in a directory the
    same blast radius — 13% of the codebase per change against 0.8% at file
    level, measured on one real repository. The rollup belongs here, after.
    """
    return sorted({path_to_module[e] for e in entities if e in path_to_module})
