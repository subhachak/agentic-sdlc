"""The release phase, when releasing means merging.

Gate 3 approval merges the pull request and the client's own automation
deploys from it. These tests pin the three things that separates that from
"call an API and hope": the revision that ships is the one the gates
approved, health is never assumed, and the way back is the way in.
"""

from __future__ import annotations

import httpx
import pytest

from app.adapters.build_deploy import github_merge as gm
from app.adapters.build_deploy.github_merge import GitHubMergeDeploy
from app.ports.build_deploy import DeployRequest


def _routed(monkeypatch, handler):
    """Point the adapter's httpx at a handler instead of the network."""
    real = httpx.AsyncClient

    def client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real(*args, **kwargs)

    monkeypatch.setattr(gm.httpx, "AsyncClient", client)


def _request(**over) -> DeployRequest:
    base = dict(
        run_id="run-1", environment="production", revision="abc123", branch="agentic/feat"
    )
    return DeployRequest(**{**base, **over})


# --- deploy ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_revision_that_ships_is_the_one_the_gates_approved(monkeypatch):
    """A commit pushed between approval and release must not ride along, so
    the merge pins the sha rather than merging whatever the head is now."""
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/pulls"):
            return httpx.Response(200, json=[{"number": 7}])
        seen["body"] = request.read().decode()
        return httpx.Response(200, json={"merged": True, "sha": "merge-sha"})

    _routed(monkeypatch, handler)
    out = await GitHubMergeDeploy("acme/app", "t").deploy(_request())

    assert out.state == "ready"
    assert "abc123" in seen["body"]


@pytest.mark.asyncio
async def test_a_merge_reports_no_health_rather_than_good_health(monkeypatch):
    """The merge mechanism succeeding says nothing about whether the thing
    works. False would be a verdict; None is the truth at that instant."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/pulls"):
            return httpx.Response(200, json=[{"number": 7}])
        return httpx.Response(200, json={"merged": True, "sha": "merge-sha"})

    _routed(monkeypatch, handler)
    out = await GitHubMergeDeploy("acme/app", "t").deploy(_request())

    assert out.deployment.succeeded is True
    assert out.deployment.healthy is None


@pytest.mark.asyncio
async def test_a_head_that_moved_since_approval_is_not_merged(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/pulls"):
            return httpx.Response(200, json=[{"number": 7}])
        return httpx.Response(409, json={"message": "head sha changed"})

    _routed(monkeypatch, handler)
    out = await GitHubMergeDeploy("acme/app", "t").deploy(_request())

    assert out.state == "failed"
    assert "changed since it was approved" in out.detail


@pytest.mark.asyncio
async def test_a_run_with_no_branch_is_refused_rather_than_defaulted(monkeypatch):
    """Merging something chosen by default would ship code no gate saw."""
    _routed(monkeypatch, lambda r: httpx.Response(500))
    out = await GitHubMergeDeploy("acme/app", "t").deploy(_request(branch=""))

    assert out.state == "failed"
    assert "nothing to merge" in out.detail


# --- observe ---------------------------------------------------------------


def _deployment_handler(states: list[str]):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/statuses"):
            index = int(request.url.path.split("/deployments/")[1].split("/")[0]) - 1
            return httpx.Response(200, json=[{"state": states[index], "target_url": "https://x"}])
        return httpx.Response(
            200,
            json=[
                {"id": i + 1, "environment": f"env{i}", "url": ""}
                for i in range(len(states))
            ],
        )

    return handler


@pytest.mark.asyncio
async def test_every_host_has_to_be_healthy(monkeypatch):
    """One green and one red is half a release, which is the state a
    rollback exists for — not a healthy one."""
    _routed(monkeypatch, _deployment_handler(["success", "failure"]))
    out = await GitHubMergeDeploy("acme/app", "t").check("merge-sha")

    assert out.deployment.healthy is False


@pytest.mark.asyncio
async def test_all_hosts_green_is_healthy(monkeypatch):
    _routed(monkeypatch, _deployment_handler(["success", "success"]))
    out = await GitHubMergeDeploy("acme/app", "t").check("merge-sha")

    assert out.deployment.healthy is True


@pytest.mark.asyncio
async def test_a_commit_no_host_has_claimed_is_pending_not_healthy(monkeypatch):
    """Automation that has not started is not automation that succeeded."""
    _routed(monkeypatch, lambda r: httpx.Response(200, json=[]))
    out = await GitHubMergeDeploy("acme/app", "t").check("merge-sha")

    assert out.state == "pending"
    assert out.deployment is None


@pytest.mark.asyncio
async def test_an_unrecognised_status_is_unknown_never_assumed_good(monkeypatch):
    _routed(monkeypatch, _deployment_handler(["something_new"]))
    out = await GitHubMergeDeploy("acme/app", "t").check("merge-sha")

    assert out.deployment.healthy is None


# --- reverse ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_rollback_without_a_working_copy_says_so_rather_than_failing_late():
    out = await GitHubMergeDeploy("acme/app", "t").rollback("merge-sha")

    assert out.state == "failed"
    assert "TARGET_WORKING_COPY" in out.detail


@pytest.mark.asyncio
async def test_a_merge_commit_is_reverted_against_its_mainline_parent(tmp_path):
    """`-m 1` is required for a merge commit and rejected for an ordinary
    one, so which to pass is asked of the commit rather than assumed from
    the configured merge method."""
    calls: list[list[str]] = []
    adapter = GitHubMergeDeploy("acme/app", "t", working_copy=tmp_path)

    def fake_git(*args: str) -> str:
        calls.append(list(args))
        if args[0] == "rev-list":
            return "merge-sha parent-a parent-b"  # two parents: a merge commit
        return "reverted-sha"

    adapter._git = fake_git
    out = await adapter.rollback("merge-sha")

    revert = next(c for c in calls if c[0] == "revert")
    assert revert[:4] == ["revert", "--no-edit", "-m", "1"]
    assert out.state == "ready"
    assert out.deployment.healthy is None


@pytest.mark.asyncio
async def test_a_squashed_commit_is_reverted_without_a_mainline(tmp_path):
    calls: list[list[str]] = []
    adapter = GitHubMergeDeploy("acme/app", "t", working_copy=tmp_path, merge_method="squash")

    def fake_git(*args: str) -> str:
        calls.append(list(args))
        if args[0] == "rev-list":
            return "squash-sha only-parent"  # one parent
        return "reverted-sha"

    adapter._git = fake_git
    await adapter.rollback("squash-sha")

    revert = next(c for c in calls if c[0] == "revert")
    assert "-m" not in revert


@pytest.mark.asyncio
async def test_a_failed_revert_is_left_for_a_person(tmp_path):
    """A cleanup that discards a half-finished revert also discards the
    evidence of why it failed."""
    adapter = GitHubMergeDeploy("acme/app", "t", working_copy=tmp_path)

    def fake_git(*args: str) -> str:
        if args[0] == "revert":
            raise RuntimeError("conflict in app/lib/format.ts")
        return "x parent"

    adapter._git = fake_git
    out = await adapter.rollback("merge-sha")

    assert out.state == "failed"
    assert "conflict" in out.detail
