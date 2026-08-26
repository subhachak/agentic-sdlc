"""The workflow file is a deployment artifact nobody was checking.

This platform has three, not two: the control plane, the execution plane,
and the workflow definition that bridges them — which lives in the client's
repository. Nothing verified it existed before dispatching.

A missing file 404s, which is survivable. A file whose inputs have drifted
is much worse: workflow_dispatch cannot decline a run for inputs it does not
declare, so the POST succeeds, the job starts, ignores what it was sent,
checks out its own ref and reports a verdict on the default branch. That
reads exactly like a passing QA result for a change it never saw.
"""

from __future__ import annotations

import httpx
import pytest

from app.adapters.work_dispatch.github_actions import GitHubActionsWorkDispatch

GOOD_WORKFLOW = """
on:
  workflow_dispatch:
    inputs:
      control_run_id:
        required: true
      correlation_id:
        required: true
      base_sha:
        required: true
      head_sha:
        required: true
"""

DRIFTED_WORKFLOW = """
on:
  workflow_dispatch:
    inputs:
      control_run_id:
        required: true
      correlation_id:
        required: true
"""


def dispatcher(monkeypatch, *, meta_status=200, body=GOOD_WORKFLOW, content_status=200):
    def handler(request: httpx.Request) -> httpx.Response:
        if "/contents/" in str(request.url):
            return httpx.Response(content_status, text=body)
        if meta_status != 200:
            return httpx.Response(meta_status, json={})
        return httpx.Response(200, json={"path": ".github/workflows/agentic-qa.yml"})

    real = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient",
        lambda *a, **k: real(*a, **{**k, "transport": httpx.MockTransport(handler)}),
    )
    return GitHubActionsWorkDispatch(
        repo="acme/thing", workflow_file="agentic-qa.yml", token="t", ref="main"
    )


@pytest.mark.asyncio
async def test_an_installed_workflow_that_speaks_the_contract_passes(monkeypatch):
    out = await dispatcher(monkeypatch).check_access()
    assert out["ok"] is True


@pytest.mark.asyncio
async def test_a_missing_workflow_is_reported_as_not_installed(monkeypatch):
    out = await dispatcher(monkeypatch, meta_status=404).check_access()
    assert out["ok"] is False
    assert "not installed" in out["detail"]


@pytest.mark.asyncio
async def test_a_workflow_whose_inputs_drifted_is_refused(monkeypatch):
    """The dangerous case. It would accept the dispatch and test its own ref."""
    out = await dispatcher(monkeypatch, body=DRIFTED_WORKFLOW).check_access()
    assert out["ok"] is False
    assert "base_sha" in out["detail"] and "head_sha" in out["detail"]


@pytest.mark.asyncio
async def test_an_unreadable_workflow_passes_but_says_it_was_not_verified(monkeypatch):
    """A token without contents:read can dispatch but cannot read the file.
    Reporting that honestly beats failing a working deployment."""
    out = await dispatcher(monkeypatch, content_status=403).check_access()
    assert out["ok"] is True
    assert "could not be read" in out["detail"]


@pytest.mark.asyncio
async def test_an_unreachable_github_is_an_answer_not_an_exception(monkeypatch):
    real = httpx.AsyncClient

    def boom(request):
        raise httpx.ConnectError("no route", request=request)

    monkeypatch.setattr(
        httpx, "AsyncClient",
        lambda *a, **k: real(*a, **{**k, "transport": httpx.MockTransport(boom)}),
    )
    d = GitHubActionsWorkDispatch(
        repo="acme/thing", workflow_file="agentic-qa.yml", token="t", ref="main"
    )
    out = await d.check_access()
    assert out["ok"] is False
    assert "could not reach" in out["detail"]
