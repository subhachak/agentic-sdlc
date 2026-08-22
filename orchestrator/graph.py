"""The QA pipeline as a LangGraph state graph.

Linear phases with one conditional branch: if the test-plan gate rejects
the proposed scenarios, the graph stops at plan_rejected instead of
running tests against an untrustworthy plan. Every node is a plain
function over PipelineState — see orchestrator/nodes/.
"""
from __future__ import annotations

from langgraph.graph import END, StateGraph

from orchestrator.nodes import (
    diff_analysis,
    evidence,
    gate,
    plan_rejected,
    report,
    test_data,
    test_gen,
    test_plan,
    test_run,
)
from orchestrator.state import PipelineState


def _plan_gate_router(state: PipelineState) -> str:
    return "continue" if state["test_plan_gate_passed"] else "reject"


def build_graph():
    g = StateGraph(PipelineState)

    g.add_node("diff_analysis", diff_analysis.run)
    g.add_node("test_plan", test_plan.run)
    g.add_node("plan_rejected", plan_rejected.run)
    g.add_node("test_data", test_data.run)
    g.add_node("test_gen", test_gen.run)
    g.add_node("test_run", test_run.run)
    g.add_node("evidence", evidence.run)
    g.add_node("gate", gate.run)
    g.add_node("report", report.run)

    g.set_entry_point("diff_analysis")
    g.add_edge("diff_analysis", "test_plan")
    g.add_conditional_edges(
        "test_plan",
        _plan_gate_router,
        {"continue": "test_data", "reject": "plan_rejected"},
    )
    g.add_edge("plan_rejected", END)
    g.add_edge("test_data", "test_gen")
    g.add_edge("test_gen", "test_run")
    g.add_edge("test_run", "evidence")
    g.add_edge("evidence", "gate")
    g.add_edge("gate", "report")
    g.add_edge("report", END)

    return g.compile()
