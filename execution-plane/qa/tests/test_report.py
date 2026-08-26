"""Reporting is the only thing that writes to GitHub, and it runs in the
privileged job. What it posts, and how many issues it files, is the part a
human actually sees.
"""
from __future__ import annotations

import pytest

from orchestrator.nodes import report


@pytest.fixture
def calls(monkeypatch):
    """Capture what is published, through the port rather than around it.

    This used to patch `report.github_api` directly, which tested that one
    vendor's functions were called. Substituting a publisher tests the thing
    that actually has to hold: whatever the destination, the same verdict and
    the same defects are handed to it.
    """
    recorded = {"comments": [], "issues": []}

    class Recording:
        contract_version = 1

        def capabilities(self):
            return {"name": "recording", "comments": True, "raises_defects": True}

        def publish_verdict(self, destination, body):
            recorded["comments"].append(body)
            return "https://gh/comment/1"

        def raise_defect(self, destination, title, body, labels):
            recorded["issues"].append(title)
            return f"https://gh/issue/{len(recorded['issues'])}"

    monkeypatch.setattr(report, "build_publisher", Recording)
    return recorded


BASE = {
    "repo": "acme/demo",
    "pr_number": 7,
    "change_summary": "added a status filter",
    "test_plan": [{"id": "s1", "title": "filter by Approved", "type": "functional", "priority": "P1"}],
    "test_assignments": [{"scenario_id": "s1", "mode": "generated"}],
    "evidence_summary": {"screenshot_count": 3, "trace_count": 1, "html_report": "evidence/html-report/index.html"},
}


def test_pass_posts_one_comment_and_files_no_issues(calls):
    result = report.run({**BASE, "test_plan_gate_passed": True, "gate_passed": True})

    assert len(calls["comments"]) == 1
    assert calls["issues"] == []
    assert "PASSED" in calls["comments"][0]
    assert result["defects_created"] == []


def test_fail_files_one_issue_per_failing_scenario_plus_a_summary(calls):
    result = report.run({
        **BASE,
        "test_plan_gate_passed": True,
        "gate_passed": False,
        "failing_scenarios": ["filter by Approved", "empty state"],
        "gate_reasons": ["2 test(s) failed"],
    })

    assert calls["issues"] == ["[Auto QA] filter by Approved", "[Auto QA] empty state"]
    assert len(calls["comments"]) == 1
    assert "FAILED" in calls["comments"][0]
    assert len(result["defects_created"]) == 2


def test_rejected_plan_posts_the_stop_comment_and_files_nothing(calls):
    result = report.run({
        **BASE,
        "test_plan_gate_passed": False,
        "test_plan_attempts": 3,
        "test_plan_gate_reasons": ["s2: rejected — no expected_outcome"],
    })

    assert calls["issues"] == []
    body = calls["comments"][0]
    assert "STOPPED at test-plan gate" in body
    assert "3 attempt(s)" in body
    assert result["defects_created"] == []


def test_evidence_links_the_actions_run_instead_of_runner_paths(calls, monkeypatch):
    monkeypatch.setenv("GITHUB_REPOSITORY", "acme/demo")
    monkeypatch.setenv("GITHUB_RUN_ID", "12345")

    report.run({**BASE, "test_plan_gate_passed": True, "gate_passed": True})

    body = calls["comments"][0]
    assert "https://github.com/acme/demo/actions/runs/12345" in body
    assert "qa-evidence-pr-7" in body
    assert "/home/runner" not in body


def test_evidence_block_degrades_gracefully_outside_actions(calls, monkeypatch):
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    monkeypatch.delenv("GITHUB_RUN_ID", raising=False)

    report.run({**BASE, "test_plan_gate_passed": True, "gate_passed": True})

    assert "3 screenshots" in calls["comments"][0]


def test_unassigned_scenarios_are_visible_in_the_plan_table(calls):
    report.run({
        **BASE,
        "test_assignments": [],
        "test_plan_gate_passed": True,
        "gate_passed": False,
        "failing_scenarios": [],
        "gate_reasons": ["only 0/1 planned scenarios got a test assignment"],
    })

    assert "not assigned" in calls["comments"][0]


def test_a_run_with_no_change_request_still_reports(monkeypatch):
    """A nightly regression against a branch has no pull request. The
    pipeline used to refuse to start; now it runs and simply posts nowhere,
    which is the honest outcome — there is no thread to post to."""
    from orchestrator.adapters.silent_publisher import SilentPublisher
    from orchestrator.ports_publish import Destination

    publisher = SilentPublisher()
    assert publisher.publish_verdict(Destination(repo="acme/demo"), "body") == ""
    assert publisher.capabilities()["raises_defects"] is False


def test_the_github_publisher_declines_to_comment_with_no_pull_request():
    """Nowhere to comment is not a failure of the QA run, so it returns an
    empty url rather than raising."""
    from orchestrator.adapters.github_publisher import GitHubPublisher
    from orchestrator.ports_publish import Destination

    out = GitHubPublisher().publish_verdict(
        Destination(repo="acme/demo", change_request_id=""), "body"
    )
    assert out == ""
