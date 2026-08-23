"""Terminal node — the test-plan gate rejected the proposed plan after every
revision attempt. Stops here rather than continuing with untestable
scenarios.

This node deliberately makes no GitHub call. Every write to GitHub happens
in the report phase, which runs as a separate, higher-privilege job that
never executes agent-generated code — see .github/workflows/agentic-qa.yml.
"""
from __future__ import annotations

from orchestrator.state import PipelineState


def run(state: PipelineState) -> PipelineState:
    return {
        **state,
        "gate_passed": False,
        "gate_reasons": state.get("test_plan_gate_reasons", []),
        "failing_scenarios": [],
        "defects_created": [],
    }
