"""Port: tell someone what QA found.

The last hard coupling to one vendor. `report.py` imported `github_api` and
called `post_pr_comment` and `create_or_update_issue` directly, so the
platform could run QA anywhere and only *tell anyone about it* on GitHub. A
client on GitLab or Azure DevOps had to fork the pipeline — the exact
failure the ports exist to prevent, and the one place it survived.

Two verbs, because they have different lifetimes. A verdict belongs to one
change and is posted where that change is being reviewed. A defect outlives
the change and belongs in whatever tracks work, which is often a different
system entirely — a GitLab merge request note and a Jira issue is an
ordinary combination.

Neither takes a pull request number. QA that runs nightly against a branch
has no change request, and a contract that demanded one would forbid a
legitimate run — the same mistake `--pr-number required=True` made.
"""

from __future__ import annotations

from typing import Any, Protocol

PUBLISH_CONTRACT_VERSION = 1


class Destination(dict):
    """Where a result should go, in the client's own terms.

    A plain dict for the same reason the other cross-boundary shapes are:
    the producer and the consumer are separately deployed, and a schema
    shared across that boundary needs versioning in two places at once.

    Keys: repo, change_request_id (may be empty), branch, run_url.
    """


class ResultPublisher(Protocol):
    contract_version: int

    def capabilities(self) -> dict[str, Any]: ...
    """What this publisher can do.

    Keys: comments (bool), raises_defects (bool), name (str).

    Read before it is asked. A publisher that cannot raise defects is not an
    error — plenty of teams triage from the run itself — but the pipeline
    records that the defect was not filed anywhere rather than assuming it
    was.
    """

    def publish_verdict(self, destination: Destination, body: str) -> str: ...
    """Post the QA outcome where the change is being reviewed.

    Returns a URL, or an empty string when the publisher has nowhere to put
    one. Never raises for an absent destination: a run with no change
    request is a legitimate run, and failing it over the absence of a
    comment thread would fail the wrong thing."""

    def raise_defect(
        self, destination: Destination, title: str, body: str, labels: list[str]
    ) -> str: ...
    """Record a failure that outlives this change. Returns a URL or ""."""
