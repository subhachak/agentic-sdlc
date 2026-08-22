"""Phase 8 — Report: the audit trail this whole pipeline exists to produce.

Pass: one PR comment summarizing plan, run, and evidence.
Fail: one GitHub issue per failing scenario, each carrying its own
evidence pointer, plus a PR comment linking all of them. Traceability
runs both directions — from requirement to test to result.
"""
from __future__ import annotations

from orchestrator import github_api
from orchestrator.state import PipelineState


def _plan_table(state: PipelineState) -> str:
    rows = ["| Scenario | Type | Priority | Mode |", "|---|---|---|---|"]
    assignments = {a["scenario_id"]: a for a in state.get("test_assignments", [])}
    for sc in state.get("test_plan", []):
        a = assignments.get(sc["id"], {})
        rows.append(f"| {sc['title']} | {sc['type']} | {sc['priority']} | {a.get('mode', '?')} |")
    return "\n".join(rows)


def run(state: PipelineState) -> PipelineState:
    repo = state["repo"]
    pr_number = state["pr_number"]
    plan_table = _plan_table(state)
    evidence = state.get("evidence_summary", {})

    if state["gate_passed"]:
        body = (
            f"## Agentic QA — PASSED\n\n"
            f"**Change:** {state['change_summary']}\n\n"
            f"**Test plan** ({len(state.get('test_plan', []))} scenarios):\n{plan_table}\n\n"
            f"**Data:** {state.get('seed_summary', '')}\n\n"
            f"**Evidence:** {evidence.get('screenshot_count', 0)} screenshots, "
            f"{evidence.get('trace_count', 0)} traces captured. "
            f"HTML report: `{evidence.get('html_report')}`\n\n"
            f"All planned scenarios ran and passed."
        )
        comment_url = github_api.post_pr_comment(repo, pr_number, body)
        return {**state, "pr_comment_url": comment_url, "defects_created": []}

    # --- fail path: one issue per failing scenario ---
    defect_urls = []
    for title in state.get("failing_scenarios", []):
        issue_body = (
            f"**Auto-filed by the agentic QA pipeline**\n\n"
            f"PR: #{pr_number} ({repo})\n"
            f"Change: {state['change_summary']}\n\n"
            f"Failing test: `{title}`\n\n"
            f"Evidence: {evidence.get('screenshot_count', 0)} screenshots, "
            f"{evidence.get('trace_count', 0)} traces at `{evidence.get('html_report')}`\n\n"
            f"Gate reasons:\n" + "\n".join(f"- {r}" for r in state.get("gate_reasons", []))
        )
        url = github_api.create_issue(
            repo, title=f"[Auto QA] {title}", body=issue_body, labels=["agentic-qa", "defect"]
        )
        defect_urls.append(url)

    summary_body = (
        f"## Agentic QA — FAILED\n\n"
        f"**Change:** {state['change_summary']}\n\n"
        f"**Test plan:**\n{plan_table}\n\n"
        f"**Gate reasons:**\n" + "\n".join(f"- {r}" for r in state.get("gate_reasons", [])) + "\n\n"
        f"**Defects filed:**\n" + "\n".join(f"- {u}" for u in defect_urls)
    )
    comment_url = github_api.post_pr_comment(repo, pr_number, summary_body)

    return {**state, "pr_comment_url": comment_url, "defects_created": defect_urls}
