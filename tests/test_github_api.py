"""Filing the same defect twice on every re-run makes the issue tracker
useless, which is the one artifact a human is expected to work from.
"""
from __future__ import annotations

import pytest

from orchestrator import github_api


class _FakeResponse:
    def __init__(self, payload, links=None):
        self._payload = payload
        self.links = links or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        return None


@pytest.fixture
def gh(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    monkeypatch.delenv("DRY_RUN", raising=False)
    calls = {"get": [], "post": [], "patch": []}

    def fake_get(url, **kw):
        calls["get"].append(url)
        return _FakeResponse(gh.existing)

    def fake_post(url, **kw):
        calls["post"].append((url, kw.get("json", {})))
        return _FakeResponse({"html_url": "https://gh/issue/new"})

    def fake_patch(url, **kw):
        calls["patch"].append((url, kw.get("json", {})))
        return _FakeResponse({})

    monkeypatch.setattr(github_api.requests, "get", fake_get)
    monkeypatch.setattr(github_api.requests, "post", fake_post)
    monkeypatch.setattr(github_api.requests, "patch", fake_patch)
    gh.existing = []
    gh.calls = calls
    return gh


def test_a_new_defect_creates_an_issue(gh):
    url = github_api.create_or_update_issue("acme/demo", "[Auto QA] boom", "body", ["agentic-qa"])

    assert url == "https://gh/issue/new"
    assert gh.calls["post"][0][0].endswith("/repos/acme/demo/issues")


def test_a_recurring_defect_comments_instead_of_filing_again(gh):
    gh.existing = [{"number": 42, "title": "[Auto QA] boom", "state": "open",
                    "html_url": "https://gh/issue/42"}]

    url = github_api.create_or_update_issue("acme/demo", "[Auto QA] boom", "body", ["agentic-qa"])

    assert url == "https://gh/issue/42"
    posted_urls = [u for u, _ in gh.calls["post"]]
    assert posted_urls == ["https://api.github.com/repos/acme/demo/issues/42/comments"]
    assert "recurred" in gh.calls["post"][0][1]["body"]


def test_a_recurring_defect_reopens_a_closed_issue(gh):
    gh.existing = [{"number": 42, "title": "[Auto QA] boom", "state": "closed",
                    "html_url": "https://gh/issue/42"}]

    github_api.create_or_update_issue("acme/demo", "[Auto QA] boom", "body", ["agentic-qa"])

    assert gh.calls["patch"] == [
        ("https://api.github.com/repos/acme/demo/issues/42", {"state": "open"})
    ]


def test_pull_requests_are_not_mistaken_for_issues(gh):
    gh.existing = [{"number": 9, "title": "[Auto QA] boom", "state": "open",
                    "html_url": "https://gh/pull/9", "pull_request": {}}]

    github_api.create_or_update_issue("acme/demo", "[Auto QA] boom", "body", ["agentic-qa"])

    assert gh.calls["post"][0][0].endswith("/repos/acme/demo/issues")


def test_a_different_title_is_a_different_defect(gh):
    gh.existing = [{"number": 42, "title": "[Auto QA] something else", "state": "open",
                    "html_url": "https://gh/issue/42"}]

    github_api.create_or_update_issue("acme/demo", "[Auto QA] boom", "body", ["agentic-qa"])

    assert gh.calls["post"][0][0].endswith("/repos/acme/demo/issues")


def test_dry_run_makes_no_http_call(gh, monkeypatch, capsys):
    monkeypatch.setenv("DRY_RUN", "1")

    url = github_api.create_or_update_issue("acme/demo", "[Auto QA] boom", "body", ["agentic-qa"])

    assert url.startswith("dry-run://")
    assert gh.calls["get"] == [] and gh.calls["post"] == []
    assert "[DRY RUN]" in capsys.readouterr().out


def test_a_missing_token_fails_with_a_readable_message(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("DRY_RUN", raising=False)

    with pytest.raises(RuntimeError, match="GITHUB_TOKEN is not set"):
        github_api.post_pr_comment("acme/demo", 1, "hi")
