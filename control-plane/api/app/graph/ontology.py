"""The ontology. Fixed, and deliberately not configurable.

Clients bring their own systems of record, not their own semantics. If node
and edge types were configurable, no phase logic would be portable and every
engagement would fork the platform. Clients extend through namespaced types
(prefix `x_`), which are stored and displayed but never gated on.

Nothing here knows what a Jira issue is. Mapping a native identifier onto one
of these types is the EntityResolver port's job.
"""

from __future__ import annotations

from enum import StrEnum

EXTENSION_PREFIX = "x_"


class NodeType(StrEnum):
    PRODUCT = "PRODUCT"
    REQUIREMENT = "REQUIREMENT"
    ACCEPTANCE_CRITERION = "ACCEPTANCE_CRITERION"
    DESIGN_DECISION = "DESIGN_DECISION"
    COMPONENT = "COMPONENT"
    SOURCE_ARTIFACT = "SOURCE_ARTIFACT"
    TEST_SCENARIO = "TEST_SCENARIO"
    TEST_SCRIPT = "TEST_SCRIPT"
    TEST_RUN = "TEST_RUN"
    DEFECT = "DEFECT"
    EVIDENCE = "EVIDENCE"
    CONTROL = "CONTROL"
    ENVIRONMENT = "ENVIRONMENT"
    RELEASE = "RELEASE"
    INCIDENT = "INCIDENT"


class EdgeType(StrEnum):
    DECOMPOSES_TO = "DECOMPOSES_TO"
    SATISFIES = "SATISFIES"
    AFFECTS = "AFFECTS"
    IMPLEMENTS = "IMPLEMENTS"
    BELONGS_TO = "BELONGS_TO"
    DEPENDS_ON = "DEPENDS_ON"
    GOVERNED_BY = "GOVERNED_BY"
    VERIFIED_BY = "VERIFIED_BY"
    IMPLEMENTED_BY = "IMPLEMENTED_BY"
    EXERCISED_IN = "EXERCISED_IN"
    COVERS = "COVERS"
    PRODUCED = "PRODUCED"
    RAISED = "RAISED"
    CONTAINS = "CONTAINS"
    DEPLOYED_TO = "DEPLOYED_TO"
    IMPACTS = "IMPACTS"


# An edge is legal only between these node types. This table is the ontology;
# everything else in this module is machinery around it.
SIGNATURES: dict[EdgeType, tuple[NodeType, NodeType]] = {
    EdgeType.DECOMPOSES_TO: (NodeType.REQUIREMENT, NodeType.ACCEPTANCE_CRITERION),
    EdgeType.SATISFIES: (NodeType.DESIGN_DECISION, NodeType.ACCEPTANCE_CRITERION),
    EdgeType.AFFECTS: (NodeType.DESIGN_DECISION, NodeType.COMPONENT),
    EdgeType.IMPLEMENTS: (NodeType.SOURCE_ARTIFACT, NodeType.ACCEPTANCE_CRITERION),
    EdgeType.BELONGS_TO: (NodeType.SOURCE_ARTIFACT, NodeType.COMPONENT),
    EdgeType.DEPENDS_ON: (NodeType.COMPONENT, NodeType.COMPONENT),
    EdgeType.GOVERNED_BY: (NodeType.COMPONENT, NodeType.CONTROL),
    EdgeType.VERIFIED_BY: (NodeType.ACCEPTANCE_CRITERION, NodeType.TEST_SCENARIO),
    EdgeType.IMPLEMENTED_BY: (NodeType.TEST_SCENARIO, NodeType.TEST_SCRIPT),
    EdgeType.EXERCISED_IN: (NodeType.TEST_SCRIPT, NodeType.TEST_RUN),
    EdgeType.COVERS: (NodeType.TEST_SCENARIO, NodeType.COMPONENT),
    EdgeType.PRODUCED: (NodeType.TEST_RUN, NodeType.EVIDENCE),
    EdgeType.RAISED: (NodeType.TEST_RUN, NodeType.DEFECT),
    EdgeType.CONTAINS: (NodeType.RELEASE, NodeType.SOURCE_ARTIFACT),
    EdgeType.DEPLOYED_TO: (NodeType.RELEASE, NodeType.ENVIRONMENT),
    EdgeType.IMPACTS: (NodeType.INCIDENT, NodeType.COMPONENT),
}


class OntologyError(ValueError):
    pass


def is_extension(name: str) -> bool:
    return name.startswith(EXTENSION_PREFIX)


def validate_node_type(node_type: str) -> None:
    if is_extension(node_type):
        return
    if node_type not in set(NodeType):
        raise OntologyError(
            f"unknown node type {node_type!r}; core types are fixed, "
            f"client types must be prefixed {EXTENSION_PREFIX!r}"
        )


def validate_edge(edge_type: str, src_type: str, dst_type: str) -> None:
    """Reject an edge the ontology does not allow.

    Extension edges are stored without a signature check — the platform holds
    them for the client but never reasons about them.
    """
    validate_node_type(src_type)
    validate_node_type(dst_type)

    if is_extension(edge_type):
        return
    if edge_type not in set(EdgeType):
        raise OntologyError(
            f"unknown edge type {edge_type!r}; client types must be prefixed "
            f"{EXTENSION_PREFIX!r}"
        )

    expected_src, expected_dst = SIGNATURES[EdgeType(edge_type)]
    if (src_type, dst_type) != (expected_src, expected_dst):
        raise OntologyError(
            f"{edge_type} goes {expected_src} -> {expected_dst}, "
            f"not {src_type} -> {dst_type}"
        )
