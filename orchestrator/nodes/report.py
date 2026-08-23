"""Phase 8 — Report: the audit trail this whole pipeline exists to produce.

Pass: one PR comment summarizing plan, run, and evidence.
Fail: one GitHub issue per failing scenario, each carrying its own evidence
pointer, plus a PR comment linking all of them.
Plan rejected: one PR comment explaining why nothing ran.

This is the only module that writes to GitHub, and it runs as its own
workflow job. It reads a serialized PipelineState and executes none of the
agent-generated code the earlier phases produced.
"""
from __future__ import annotations

import os

from orchestrator import github_api
from orchestrator.state import PipelineState


def _run_url() -> str | None:
    """Link the Actions run rather than runner-local absolute paths, which
    mean nothing to somebody reading the PR."""
    repo = os.environ.get("GITHUB_REPOSITORY")
    run_id = os.environ.get("GITHUB_RUN_ID")
    if not (repo and run_id):
        return None
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    return f"{server}/{repo}/actions/runs/{run_id}"


def _evidence_block(state: PipelineState) -> str:
    evidence = state.get("evidence_summary", {})
    line = (
        f"{evidence.get('screenshot_count', 0)} screenshots, "
        f"{evidence.get('trace_count', 0)} traces, "
        f"HTML report at `{evidence.get('html_report') or 'not produced'}`"
    )
    url = _run_url()
    if url:
        pr_number = state.get("pr_number")
        line += f"\n\nDownload the `qa-evidence-pr-{pr_number}` artifact from [this run]({url})."
    return line


def _plan_table(state: PipelineState) -> str:
    rows = ["| Scenario | Type | Priority | Mode |", "|---|---|---|---|"]
    assignments = {a["scenario_id"]: a for a in state.get("test_assignments", [])}
    for sc in state.get("test_plan", []):
        a = assignments.get(sc["id"], {})
        rows.append(f"| {sc['title']} | {sc['type']} | {sc['priority']} | {a.get('mode', 'not assigned')} |")
    return "\n".join(rows)


def _bullets(items: list[str]) -> str:
    return "\n".join(f"- {i}" for i in items) if items else "- (none)"


def _report_plan_rejected(state: PipelineState) -> PipelineState:
    attempts = state.get("test_plan_attempts", 1)
    body = (
        f"## Agentic QA — STOPPED at test-plan gate\n\n"
        f"**Change:** {state.get('change_summary', 'unknown')}\n\n"
        f"The proposed test plan did not pass the testability gate after "
        f"{attempts} attempt(s):\n"
        f"{_bullets(state.get('test_plan_gate_reasons', []))}\n\n"
        f"No tests were run. Revise the scenarios (or the underlying acceptance "
        f"criteria) and re-trigger."
    )
    url = github_api.post_pr_comment(state["repo"], state["pr_number"], body)
    return {**state, "pr_comment_url": url, "defects_created": []}


def _report_pass(state: PipelineState) -> PipelineState:
    body = (
        f"## Agentic QA — PASSED\n\n"
        f"**Change:** {state['change_summary']}\n\n"
        f"**Test plan** ({len(state.get('test_plan', []))} scenarios):\n{_plan_table(state)}\n\n"
        f"**Data:** {state.get('seed_summary', '')}\n\n"
        f"**Evidence:** {_evidence_block(state)}\n\n"
        f"All planned scenarios ran and passed."
    )
    url = github_api.post_pr_comment(state["repo"], state["pr_number"], body)
    return {**state, "pr_comment_url": url, "defects_created": []}


def _report_fail(state: PipelineState) -> PipelineState:
    repo, pr_number = state["repo"], state["pr_number"]
    evidence_block = _evidence_block(state)

    defect_urls = []
    for title in state.get("failing_scenarios", []):
        issue_body = (
            f"**Auto-filed by the agentic QA pipeline**\n\n"
            f"PR: #{pr_number} ({repo})\n"
            f"Change: {state.get('change_summary', 'unknown')}\n\n"
            f"Failing test: `{title}`\n\n"
            f"**Evidence:** {evidence_block}\n\n"
            f"**Gate reasons:**\n{_bullets(state.get('gate_reasons', []))}"
        )
        defect_urls.append(
            github_api.create_or_update_issue(
                repo,
                title=f"[Auto QA] {title}",
                body=issue_body,
                labels=["agentic-qa", "defect"],
            )
        )

    summary_body = (
        f"## Agentic QA — FAILED\n\n"
        f"**Change:** {state.get('change_summary', 'unknown')}\n\n"
        f"**Test plan:**\n{_plan_table(state)}\n\n"
        f"**Gate reasons:**\n{_bullets(state.get('gate_reasons', []))}\n\n"
        f"**Evidence:** {evidence_block}\n\n"
        f"**Defects filed:**\n{_bullets(defect_urls)}"
    )
    url = github_api.post_pr_comment(repo, pr_number, summary_body)
    return {**state, "pr_comment_url": url, "defects_created": defect_urls}


def run(state: PipelineState) -> PipelineState:
    if not state.get("test_plan_gate_passed", False):
        return _report_plan_rejected(state)
    if state.get("gate_passed"):
        return _report_pass(state)
    return _report_fail(state)
