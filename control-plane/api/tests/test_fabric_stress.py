"""Adversarial tests on the context fabric.

Impact intelligence is only as good as the graph beneath it, and the graph
is only as good as its identity, its scoping and its ontology. Every test
here corresponds to a way the fabric was — or still is — able to be wrong
about what a thing *is*, which is a worse failure than being wrong about
what depends on it: a bad edge gives a bad answer, a bad identity gives a
confident answer about a different thing.

Where a gap is not yet closed it is marked xfail with the reason, so the
suite states the known shape of the fabric rather than only its strengths.
"""

from __future__ import annotations

import pytest

from app.graph.identity import node_id
from app.graph.ontology import EdgeType, NodeType, OntologyError, validate_edge
from app.graph.paths import canonical
from app.graph.projects import DEFAULT_PROJECT, project_of, scoped

CODE = "code"


# ── identity: one thing, one id ───────────────────────────────────────────


@pytest.mark.parametrize(
    "variant",
    ["./app/a.ts", "/app/a.ts", "app//a.ts", "app/./a.ts", "app/b/../a.ts", "app\\a.ts"],
)
def test_every_spelling_of_a_path_is_one_node(variant):
    """Six spellings produced six nodes for one file.

    The indexer emits clean paths, but agent-authored ones reach identity
    directly — the release phase mints a node for every file the
    implementation agent reports, and a client's coding agent chooses that
    spelling. One `./` created a phantom node no import edge pointed at, so
    the file read as unreferenced and its blast radius was empty.
    """
    assert node_id("SOURCE_ARTIFACT", CODE, canonical(variant)) == node_id(
        "SOURCE_ARTIFACT", CODE, canonical("app/a.ts")
    )


def test_case_is_preserved_because_merging_is_worse_than_duplicating():
    """Two files differing only in case are distinct on the filesystems this
    indexes. Folding case would trade a duplicate for a collision."""
    assert canonical("APP/a.ts") != canonical("app/a.ts")


def test_a_path_that_escapes_the_repository_does_not_keep_its_escape():
    assert not canonical("../../etc/passwd").startswith("..")


# ── identity: the delimiter is not escaped ────────────────────────────────


def test_the_identity_delimiter_can_be_injected():
    """`type|system|external_id` is joined without escaping, so a value
    containing the delimiter can impersonate a different triple.

    Reachable through any external id the platform does not control — a
    client work-item key, a document id, a path on a filesystem that permits
    `|`. Left failing deliberately: fixing it changes every node id ever
    written, which is a migration rather than a patch, and the fabric should
    say out loud that it has this shape.
    """
    collides = node_id("SOURCE_ARTIFACT", "code", "a|b") == node_id(
        "SOURCE_ARTIFACT", "code|a", "b"
    )
    if collides:
        pytest.xfail(
            "identity joins on '|' without escaping; two different triples share an id"
        )


# ── scoping: one project cannot be another ────────────────────────────────


def test_the_default_project_has_exactly_one_spelling():
    """`code` and `code@default` both mean the default project and are
    different nodes, so a writer using the explicit form would build a
    parallel graph nothing queries."""
    assert scoped(CODE, DEFAULT_PROJECT) == CODE
    assert project_of(CODE) == DEFAULT_PROJECT
    assert project_of("code@default") == DEFAULT_PROJECT
    assert node_id("MODULE", scoped(CODE, DEFAULT_PROJECT), "m") == node_id(
        "MODULE", CODE, "m"
    )


def test_two_projects_never_share_a_node():
    a = node_id("SOURCE_ARTIFACT", scoped(CODE, "team-a"), "app/a.ts")
    b = node_id("SOURCE_ARTIFACT", scoped(CODE, "team-b"), "app/a.ts")
    assert a != b


def test_a_project_id_cannot_smuggle_the_scope_delimiter():
    from app.graph.projects import ProjectError, validate

    for hostile in ["a@b", "a b", "../x", "x" * 64, "", "a/b", "a:b", "a\\b"]:
        with pytest.raises(ProjectError):
            validate(hostile)

    # Case is folded rather than refused, so "Acme" and "acme" are one
    # project. Deliberate: two engagements differing only in case would be
    # indistinguishable to everyone reading the console, and a graph split
    # between them is the worse outcome.
    assert validate("Acme") == validate("acme") == "acme"


# ── ontology: an edge means what the signature says ───────────────────────


def test_a_legal_edge_between_the_wrong_types_is_refused():
    with pytest.raises(OntologyError):
        validate_edge(EdgeType.IMPORTS, NodeType.REQUIREMENT, NodeType.RELEASE)


def test_an_unknown_edge_type_is_refused_unless_namespaced():
    with pytest.raises(OntologyError):
        validate_edge("INVENTED", NodeType.MODULE, NodeType.MODULE)
    # A client type is held without a signature check, and never gated on.
    validate_edge("x_depends_on_policy", NodeType.MODULE, NodeType.CONTROL)


def test_an_extension_edge_still_cannot_invent_a_node_type():
    """Extensions relax the edge signature, not the node vocabulary — a node
    type nothing understands has no projection anything can read."""
    with pytest.raises(OntologyError):
        validate_edge("x_thing", "NOT_A_NODE_TYPE", NodeType.MODULE)


# ── temporal: what the fabric cannot yet say ──────────────────────────────


@pytest.mark.xfail(
    reason="node identity carries no revision, so evidence stays attached to a "
    "file across a rewrite — CodeFile already collects sha256, unused for identity",
    strict=True,
)
def test_a_rewritten_file_is_a_different_revision():
    before = node_id("SOURCE_ARTIFACT", CODE, "app/pay.ts")  # at abc123
    after = node_id("SOURCE_ARTIFACT", CODE, "app/pay.ts")   # rewritten at def456
    assert before != after


# ── the writer that did not scope ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_release_phase_writes_into_the_run_s_own_project():
    """It hardcoded `code`, because the run's project never reached it.

    The index populated `code@<project>`; the release wrote `code`. So the
    release's CONTAINS edges pointed at file nodes that did not exist in the
    project being released, traceability from a release back to a file was
    broken for every non-default engagement, and the evidence landed in a
    different client's graph.
    """
    from app.core.context_graph import Assertion, NodeSpec
    from app.graph.paths import canonical
    from tests.graph_doubles import InMemoryContextGraph

    graph = InMemoryContextGraph()
    project = "team-a"
    code_system = scoped(CODE, project)

    # what the index wrote
    await graph.ingest("seed", "code-index", [
        Assertion(
            "IMPORTS",
            NodeSpec("SOURCE_ARTIFACT", code_system, "app/a.ts"),
            NodeSpec("SOURCE_ARTIFACT", code_system, "app/b.ts"),
        )
    ])

    # what the release phase writes, for the same file, spelled by an agent
    release = NodeSpec("RELEASE", scoped("pipeline", project), "r1")
    await graph.ingest("run-1", "release", [
        Assertion(
            "CONTAINS",
            release,
            NodeSpec("SOURCE_ARTIFACT", code_system, canonical("./app/a.ts")),
        )
    ])

    edges = await graph.phase_edges("release", project)
    assert ("CONTAINS", "r1", "app/a.ts") in edges, (
        "the release must name the same file node the index created"
    )
    # and nothing leaked into the default project
    assert await graph.phase_edges("release", DEFAULT_PROJECT) == set()
