"""Minimal GitHub REST wrapper. Only what this pipeline needs: comment on
the PR, and file an issue per failing scenario with evidence attached.
"""
from __future__ import annotations

import os

import requests

_API = "https://api.github.com"


def _headers() -> dict:
    token = os.environ["GITHUB_TOKEN"]
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
    }


def _dry_run() -> bool:
    return os.environ.get("DRY_RUN", "").lower() in ("1", "true", "yes")


def post_pr_comment(repo: str, pr_number: int, body: str) -> str:
    if _dry_run():
        print(f"\n{'='*70}\n[DRY RUN] Would post PR comment on {repo}#{pr_number}:\n{'='*70}\n{body}\n")
        return "dry-run://pr-comment"
    url = f"{_API}/repos/{repo}/issues/{pr_number}/comments"
    resp = requests.post(url, headers=_headers(), json={"body": body}, timeout=30)
    resp.raise_for_status()
    return resp.json()["html_url"]


def create_issue(repo: str, title: str, body: str, labels: list[str]) -> str:
    if _dry_run():
        print(f"\n{'='*70}\n[DRY RUN] Would create issue on {repo}: {title}\n{'='*70}\n{body}\nLabels: {labels}\n")
        return f"dry-run://issue/{title}"
    url = f"{_API}/repos/{repo}/issues"
    resp = requests.post(
        url, headers=_headers(), json={"title": title, "body": body, "labels": labels}, timeout=30
    )
    resp.raise_for_status()
    return resp.json()["html_url"]
