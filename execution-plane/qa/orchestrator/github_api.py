"""Minimal GitHub REST wrapper. Only what this pipeline needs: comment on
the PR, and file an issue per failing scenario with evidence attached.

Issue filing is idempotent. The same scenario failing on a later PR — or the
same workflow being re-run — must not produce a second issue; it adds a
recurrence comment to the existing one and reopens it if it had been closed.
"""
from __future__ import annotations

import os

import requests

_API = "https://api.github.com"
_TIMEOUT = 30


def _headers() -> dict:
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise RuntimeError(
            "GITHUB_TOKEN is not set. The report phase needs a token with "
            "issues:write and pull-requests:write, or DRY_RUN=1 to print instead."
        )
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _dry_run() -> bool:
    return os.environ.get("DRY_RUN", "").lower() in ("1", "true", "yes")


def _banner(title: str, body: str, extra: str = "") -> None:
    print(f"\n{'='*70}\n[DRY RUN] {title}\n{'='*70}\n{body}\n{extra}")


def post_pr_comment(repo: str, pr_number: int, body: str) -> str:
    if _dry_run():
        _banner(f"Would post PR comment on {repo}#{pr_number}:", body)
        return "dry-run://pr-comment"
    url = f"{_API}/repos/{repo}/issues/{pr_number}/comments"
    resp = requests.post(url, headers=_headers(), json={"body": body}, timeout=_TIMEOUT)
    resp.raise_for_status()
    return resp.json()["html_url"]


def _find_issue_by_title(repo: str, title: str, label: str) -> dict | None:
    """Look for an existing auto-filed issue with this exact title.

    Listing by label is used rather than the search API: search is eventually
    consistent, and an issue filed minutes ago by the previous run may not be
    indexed yet — which is exactly the case that would produce a duplicate.
    """
    url = f"{_API}/repos/{repo}/issues"
    params = {"labels": label, "state": "all", "per_page": 100}
    while url:
        resp = requests.get(url, headers=_headers(), params=params, timeout=_TIMEOUT)
        resp.raise_for_status()
        for issue in resp.json():
            # The issues endpoint also returns pull requests.
            if "pull_request" in issue:
                continue
            if issue["title"] == title:
                return issue
        url = resp.links.get("next", {}).get("url")
        params = None
    return None


def create_or_update_issue(repo: str, title: str, body: str, labels: list[str]) -> str:
    """File a defect, or record a recurrence on the one already filed."""
    if _dry_run():
        _banner(f"Would file or update issue on {repo}: {title}", body, f"Labels: {labels}")
        return f"dry-run://issue/{title}"

    existing = _find_issue_by_title(repo, title, labels[0])

    if existing is None:
        resp = requests.post(
            f"{_API}/repos/{repo}/issues",
            headers=_headers(),
            json={"title": title, "body": body, "labels": labels},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()["html_url"]

    number = existing["number"]
    requests.post(
        f"{_API}/repos/{repo}/issues/{number}/comments",
        headers=_headers(),
        json={"body": f"**This defect recurred.**\n\n{body}"},
        timeout=_TIMEOUT,
    ).raise_for_status()

    if existing.get("state") == "closed":
        requests.patch(
            f"{_API}/repos/{repo}/issues/{number}",
            headers=_headers(),
            json={"state": "open"},
            timeout=_TIMEOUT,
        ).raise_for_status()

    return existing["html_url"]
