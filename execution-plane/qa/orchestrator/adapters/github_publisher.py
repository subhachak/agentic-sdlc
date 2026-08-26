"""The shipped ResultPublisher: GitHub pull request comments and issues.

Behaviour unchanged — the same two calls report.py made directly — moved
behind the port so a client on GitLab or Azure DevOps writes an adapter
instead of forking the pipeline.
"""

from __future__ import annotations

from typing import Any

from orchestrator import github_api
from orchestrator.ports_publish import PUBLISH_CONTRACT_VERSION, Destination


class GitHubPublisher:
    contract_version = PUBLISH_CONTRACT_VERSION

    def capabilities(self) -> dict[str, Any]:
        return {"name": "github", "comments": True, "raises_defects": True}

    def publish_verdict(self, destination: Destination, body: str) -> str:
        change = destination.get("change_request_id")
        if not change:
            # A nightly run against a branch has no pull request. Nowhere to
            # comment is not a failure of the QA run.
            return ""
        return github_api.post_pr_comment(destination.get("repo", ""), int(change), body)

    def raise_defect(
        self, destination: Destination, title: str, body: str, labels: list[str]
    ) -> str:
        return github_api.create_or_update_issue(
            destination.get("repo", ""), title, body, labels
        )
