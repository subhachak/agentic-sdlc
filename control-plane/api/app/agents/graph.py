"""Linear pipeline graph. No dynamic supervisor routing is needed at this
phase — the only branching is "did the human approve this gate", enforced
via conditional edges so a rejection actually halts the pipeline instead of
barreling forward (silent auto-progression is exactly what this pipeline
must never do).
"""

from typing import Any

from langgraph.graph import END, START, StateGraph

from app.agents.state import PipelineState
from app.core.audit import NodeFn


def _approved(state: dict[str, Any], decision_key: str) -> bool:
    decision = state.get(decision_key)
    if decision is None:
        return False
    approved = getattr(decision, "approved", None)
    if approved is None and isinstance(decision, dict):
        approved = decision.get("approved")
    return bool(approved)


def _after_gate(decision_key: str, next_node: str):
    def router(state: dict[str, Any]) -> str:
        return next_node if _approved(state, decision_key) else END

    return router


def build_graph(nodes: dict[str, NodeFn], checkpointer=None):
    graph = StateGraph(PipelineState)
    for name, fn in nodes.items():
        graph.add_node(name, fn)

    graph.add_edge(START, "requirements_intake")
    graph.add_edge("requirements_intake", "requirements_synthesis")
    graph.add_edge("requirements_synthesis", "ambiguity_check")
    graph.add_edge("ambiguity_check", "gate_1")
    graph.add_conditional_edges("gate_1", _after_gate("gate1_decision", "design_proposal"))
    graph.add_edge("design_proposal", "gate_2")
    graph.add_conditional_edges("gate_2", _after_gate("gate2_decision", "test_case_generation"))
    graph.add_edge("test_case_generation", "gate_3")
    graph.add_conditional_edges("gate_3", _after_gate("gate3_decision", "build_deploy_stub"))
    graph.add_edge("build_deploy_stub", END)

    return graph.compile(checkpointer=checkpointer)
