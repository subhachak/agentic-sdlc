"""One impact calculation, and what it has to be able to say.

Three implementations disagreed. On apps/web/app/lib/format.ts the design
gate reported a change reaching app/app that QA never required a test for,
while QA required app/blog the design gate never named — so a change could
pass a containment check and then be tested against a different set.
"""

from app.core.impact import (
    SEMANTICS,
    Assessment,
    ChangeSet,
    Edge,
    Policy,
    assess,
    roll_up,
)


def imports(*pairs: tuple[str, str]) -> list[Edge]:
    """source imports target."""
    return [Edge(type="IMPORTS", source=s, target=t) for s, t in pairs]


def test_impact_flows_against_the_import_edge():
    """If b changes, a is affected — a imports b, not the other way round."""
    out = assess(ChangeSet(("b.ts",)), imports(("a.ts", "b.ts")))
    assert out.direct == ["a.ts"]
    assert out.transitive == []


def test_a_path_says_why():
    out = assess(ChangeSet(("c.ts",)), imports(("a.ts", "b.ts"), ("b.ts", "c.ts")))
    path = next(p for p in out.paths if p.entity == "a.ts")
    assert [e for e, _ in path.hops] == ["IMPORTS", "IMPORTS"]
    assert path.depth == 2


def test_depth_is_the_policy_and_is_honoured():
    edges = imports(("a.ts", "b.ts"), ("b.ts", "c.ts"), ("c.ts", "d.ts"))
    shallow = assess(ChangeSet(("d.ts",)), edges, policy=Policy(max_depth=1))
    assert shallow.affected == ["c.ts"]
    deep = assess(ChangeSet(("d.ts",)), edges, policy=Policy(max_depth=3))
    assert deep.affected == ["a.ts", "b.ts", "c.ts"]


def test_confidence_compounds_with_distance():
    """Two derived hops is a weaker claim than one, and a path that never
    says so overstates itself the further it goes."""
    out = assess(ChangeSet(("c.ts",)), imports(("a.ts", "b.ts"), ("b.ts", "c.ts")))
    near = next(p for p in out.paths if p.entity == "b.ts")
    far = next(p for p in out.paths if p.entity == "a.ts")
    assert far.confidence < near.confidence


def test_the_strongest_reason_wins_not_the_first_one_found():
    """Reporting whichever path was found first makes the answer depend on
    edge ordering, which is not a property of the codebase."""
    edges = [
        Edge(type="IMPORTS", source="a.ts", target="c.ts"),
        Edge(type="IMPORTS", source="a.ts", target="b.ts"),
        Edge(type="IMPORTS", source="b.ts", target="c.ts"),
    ]
    out = assess(ChangeSet(("c.ts",)), edges)
    direct = next(p for p in out.paths if p.entity == "a.ts")
    assert direct.depth == 1


def test_an_edge_that_carries_risk_but_not_test_scope():
    """A service deployed alongside another carries operational risk without
    obliging a regression test."""
    assert SEMANTICS["DEPLOYED_TO"].test_obligation is False
    out = assess(
        ChangeSet(("svc-a",)),
        [Edge(type="DEPLOYED_TO", source="svc-a", target="prod")],
        policy=Policy(edges=frozenset({"DEPLOYED_TO"})),
    )
    assert out.affected == ["prod"]
    assert out.test_obligations == []


def test_an_unknown_relationship_is_reported_not_traversed():
    """A client's namespaced edge with no declared semantics is stored and
    displayed, never silently walked as though its meaning were understood."""
    out = assess(
        ChangeSet(("b.ts",)),
        [Edge(type="x_depends_on_policy", source="a.ts", target="b.ts")],
    )
    assert out.affected == []
    assert any("x_depends_on_policy" in s for s in out.blind_spots)


def test_a_change_nothing_owns_is_named_rather_than_ignored():
    """An impact set that quietly excludes what it could not resolve reads as
    completeness."""
    out = assess(ChangeSet(("stray.ts",)), imports(("a.ts", "b.ts")), known={"a.ts", "b.ts"})
    assert out.unmapped == ["stray.ts"]
    assert any("no indexed module" in s for s in out.blind_spots)


def test_the_assessment_carries_what_produced_it():
    out = assess(ChangeSet(("b.ts",)), imports(("a.ts", "b.ts")), snapshot={"commit": "abc123"})
    body = out.as_dict()
    assert body["engine_version"]
    assert body["policy"]["version"]
    assert body["snapshot"]["commit"] == "abc123"


def test_rollup_happens_after_traversal_not_before():
    """Rolling up first gave every file in a directory the same blast radius
    — 13% of the codebase per change against 0.8% at file level."""
    edges = imports(("mod-a/one.ts", "mod-b/two.ts"))
    out = assess(ChangeSet(("mod-b/two.ts",)), edges)
    p2m = {"mod-a/one.ts": "mod-a", "mod-b/two.ts": "mod-b", "mod-a/other.ts": "mod-a"}
    # mod-a is reached because one of its files is, not because a sibling was.
    assert roll_up(out.affected, p2m) == ["mod-a"]
    assert "mod-a/other.ts" not in out.affected


def test_the_same_inputs_give_the_same_answer():
    edges = imports(("a.ts", "b.ts"), ("b.ts", "c.ts"))
    first = assess(ChangeSet(("c.ts",)), edges).as_dict()
    second = assess(ChangeSet(("c.ts",)), edges).as_dict()
    assert first == second
