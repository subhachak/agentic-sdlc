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


def _after_implementation(state: dict[str, Any]) -> str:
    change = state.get("implementation") or {}
    return "qa_execution" if change.get("files") else END


def _after_qa(state: dict[str, Any]) -> str:
    result = state.get("qa_result") or {}
    return "gate_3" if result.get("state") == "succeeded" else END


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
    graph.add_edge("test_case_generation", "implementation")
    # A change that was blocked or refused never reaches a browser, and never
    # reaches a release gate.
    graph.add_conditional_edges("implementation", _after_implementation)
    # A QA phase that failed or timed out must not reach a release gate — the
    # run ends instead, with the reason already in its status.
    graph.add_conditional_edges("qa_execution", _after_qa)
    graph.add_conditional_edges("gate_3", _after_gate("gate3_decision", "release"))
    graph.add_edge("release", END)

    return graph.compile(checkpointer=checkpointer)
