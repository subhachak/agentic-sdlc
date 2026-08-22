"""Phase 1 — Discovery for this PR: what changed, and what does it touch.

Agent proposes a summary. No gate here (nothing to be "ready" yet) — this
phase just turns a raw diff into structured context for the test-plan node.
"""
from __future__ import annotations

from orchestrator.llm import ask_json
from orchestrator.state import PipelineState

SYSTEM = """You are a QA discovery agent. Given a git diff and known feature
context, summarize what changed in plain language and list the affected
user-facing areas (routes, components, API endpoints). Be concrete — name
routes and elements, don't generalize. Output JSON:
{
  "change_summary": "...",
  "affected_areas": ["/claims (status filter added)", "..."]
}"""


def run(state: PipelineState) -> PipelineState:
    diff = state["diff_text"]
    features = state.get("features_context", {})

    user = (
        f"Known features (for context, may be incomplete for new work):\n"
        f"{features}\n\n"
        f"Git diff for this PR:\n```diff\n{diff}\n```"
    )
    result = ask_json(SYSTEM, user)

    return {
        **state,
        "change_summary": result["change_summary"],
        "affected_areas": result["affected_areas"],
    }
