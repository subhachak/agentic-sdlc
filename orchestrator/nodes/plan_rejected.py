"""Terminal node — the test-plan gate rejected the proposed plan. Stops
here rather than continuing with untestable scenarios. Posts why, so a
human can fix the requirement or re-trigger, same pattern as every other
gate in this pipeline.
"""
from __future__ import annotations

from orchestrator import github_api
from orchestrator.state import PipelineState


def run(state: PipelineState) -> PipelineState:
    body = (
        f"## Agentic QA — STOPPED at test-plan gate\n\n"
        f"**Change:** {state['change_summary']}\n\n"
        f"The proposed test plan did not pass the testability gate:\n"
        + "\n".join(f"- {r}" for r in state.get("test_plan_gate_reasons", []))
        + "\n\nNo tests were run. Revise the scenarios (or the underlying "
        "acceptance criteria) and re-trigger."
    )
    comment_url = github_api.post_pr_comment(state["repo"], state["pr_number"], body)
    return {**state, "pr_comment_url": comment_url, "gate_passed": False, "defects_created": []}
