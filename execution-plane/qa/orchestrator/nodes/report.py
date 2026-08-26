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

from orchestrator.ports_publish import Destination


def build_publisher():
    """Which publisher this deployment uses.

    A factory rather than a literal, so a client on GitLab or Azure DevOps
    writes an adapter instead of editing this node. `silent` is chosen when
    there is nowhere to post — a nightly run against a branch has no review
    thread, and that is a legitimate run rather than a misconfiguration.
    """
    import os

    if os.environ.get("QA_PUBLISHER", "github") == "silent":
        from orchestrator.adapters.silent_publisher import SilentPublisher

        return SilentPublisher()
    from orchestrator.adapters.github_publisher import GitHubPublisher

    return GitHubPublisher()


def _destination(state: PipelineState) -> Destination:
    return Destination(
        repo=state.get("repo", ""),
        # Empty rather than absent when there is no change request, so a
        # publisher can tell "nowhere to post" from "not told where".
        change_request_id=str(state.get("pr_number") or ""),
        branch=state.get("head_ref", ""),
    )
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


def _observed_block(state) -> str:
    """What the run demonstrably exercised, and what it produced worth keeping.

    Distinct from the blast-radius block above it: that says what should have
    been tested, this says what actually was. A reviewer comparing the two is
    the point.
    """
    observed = state.get("observed_coverage") or {}
    lines: list[str] = []

    modules = sorted({m for entry in observed.values() for m in entry.get("modules", [])})
    lines.append(f"Modules exercised by this run: {', '.join(modules) or 'none'}")

    gaps = state.get("coverage_gaps_observed") or {}
    if gaps:
        lines.append(
            f"Files reached: {len(gaps.get('files_reached', []))}"
            f"/{gaps.get('reachable_total', 0)} servable files "
            f"({gaps.get('file_coverage', 0):.0%})"
        )
        if gaps.get("files_never_reached"):
            lines.append(
                "Never reached by any test in this run: "
                + ", ".join(gaps["files_never_reached"])
            )
        if gaps.get("routes_never_requested"):
            lines.append("Routes never requested: " + ", ".join(gaps["routes_never_requested"]))

    candidates = state.get("promotion_candidates") or []
    gap_closers = [c for c in candidates if c["closes_coverage_gap"]]
    if gap_closers:
        lines.append(
            "Generated specs worth promoting (they cover modules the library does not): "
            + ", ".join(f"{c['script_id']} -> {', '.join(c['new_modules'])}" for c in gap_closers)
        )
    elif candidates:
        lines.append(f"{len(candidates)} generated spec(s) passed and could be promoted")

    return _bullets(lines)


def _blast_radius_block(state) -> str:
    """What the dependency graph obliged this run to re-test, and what it
    could not. Stated on the PR because a reviewer deciding whether to merge
    needs to know which impacted areas nothing exercised — that is the part
    a green tick otherwise hides.
    """
    scope = state.get("regression_scope") or {}
    impacted = scope.get("impacted_components") or []
    if not impacted:
        return "_no mapped modules were impacted by this change_"

    required = state.get("required_regressions") or []
    gaps = state.get("coverage_gaps") or []
    failed = state.get("required_regressions_failed") or []
    missing = state.get("required_regressions_missing") or []

    lines = [f"Impacted modules: {', '.join(impacted)}"]
    if required:
        verdict = "failed" if failed or missing else "passed"
        lines.append(f"Required regression scripts ({verdict}): {', '.join(required)}")
    if failed:
        lines.append(f"Failed: {', '.join(failed)}")
    if missing:
        lines.append(f"Did not run: {', '.join(missing)}")
    if gaps:
        lines.append(f"No regression coverage: {', '.join(gaps)}")
    return _bullets(lines)


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
    url = build_publisher().publish_verdict(_destination(state), body)
    return {**state, "pr_comment_url": url, "defects_created": []}


def _report_pass(state: PipelineState) -> PipelineState:
    body = (
        f"## Agentic QA — PASSED\n\n"
        f"**Change:** {state['change_summary']}\n\n"
        f"**Test plan** ({len(state.get('test_plan', []))} scenarios):\n{_plan_table(state)}\n\n"
        f"**Blast radius:**\n{_blast_radius_block(state)}\n\n"
        f"**Coverage observed:**\n{_observed_block(state)}\n\n"
        f"**Data:** {state.get('seed_summary', '')}\n\n"
        f"**Evidence:** {_evidence_block(state)}\n\n"
        f"All planned scenarios and required regressions ran and passed."
    )
    url = build_publisher().publish_verdict(_destination(state), body)
    return {**state, "pr_comment_url": url, "defects_created": []}


def _report_fail(state: PipelineState) -> PipelineState:
    repo, pr_number = state.get("repo", ""), state.get("pr_number") or ""
    publisher = build_publisher()
    destination = _destination(state)
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
        filed = publisher.raise_defect(
            destination,
            title=f"[Auto QA] {title}",
            body=issue_body,
            labels=["agentic-qa", "defect"],
        )
        if filed:
            defect_urls.append(filed)

    summary_body = (
        f"## Agentic QA — FAILED\n\n"
        f"**Change:** {state.get('change_summary', 'unknown')}\n\n"
        f"**Test plan:**\n{_plan_table(state)}\n\n"
        f"**Blast radius:**\n{_blast_radius_block(state)}\n\n"
        f"**Gate reasons:**\n{_bullets(state.get('gate_reasons', []))}\n\n"
        f"**Evidence:** {evidence_block}\n\n"
        f"**Defects filed:**\n{_bullets(defect_urls)}"
    )
    url = publisher.publish_verdict(destination, summary_body)
    # Recorded, not inferred. A publisher that cannot raise defects leaves
    # this empty, and a reader must be able to tell that from "nothing
    # failed" — so the capability travels with the result.
    return {
        **state,
        "pr_comment_url": url,
        "defects_created": defect_urls,
        "defects_filed_anywhere": bool(publisher.capabilities().get("raises_defects")),
    }


def run(state: PipelineState) -> PipelineState:
    if not state.get("test_plan_gate_passed", False):
        return _report_plan_rejected(state)
    if state.get("gate_passed"):
        return _report_pass(state)
    return _report_fail(state)
