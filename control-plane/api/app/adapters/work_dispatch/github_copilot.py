"""Hand the implementation phase to GitHub's Copilot cloud agent.

A client-provided agent, in the sense that matters: the platform does not
write the code, does not choose the model, and cannot see the reasoning. It
states the work, waits, and then reviews what came back against the design
the graph already approved.

That review is the whole point. An in-process agent can be refused before its
edits reach a branch; this one cannot. It works in its own environment and
opens a pull request, so containment here is *detection*, not prevention —
the pull request exists whatever the verdict, and a refusal means the run
fails with the branch left for a human rather than the change being silently
dropped. Saying so plainly is more useful than implying a control that is not
there.

API shapes are taken from GitHub's published OpenAPI description rather than
from memory:

    POST /agents/repos/{owner}/{repo}/tasks   {prompt, base_ref, ...}  -> {id}
    GET  /agents/repos/{owner}/{repo}/tasks/{id}
        state: queued | in_progress | completed | failed
             | idle | waiting_for_user | timed_out | cancelled
        artifacts[]: {provider, type: "pull"|"branch", data}
"""

from __future__ import annotations

from typing import Any

import httpx

from app.ports.work_dispatch import DispatchHandle, DispatchResult

_API = "https://api.github.com"
_TIMEOUT = 30.0

# States the task can still leave on its own. `idle` and `waiting_for_user`
# are not progress, but they are not failure either — the agent is asking for
# something in GitHub. They stay pending so the deadline ledger decides, and
# the detail says which, because "still running" and "waiting for you" call
# for different responses from whoever is watching.
_PENDING = {"queued", "in_progress", "idle", "waiting_for_user"}
_FAILED = {"failed", "cancelled"}


class GitHubCopilotWorkDispatch:
    """WorkDispatch over the Copilot cloud agent's task API.

    Implements the same two methods as the CI adapter because it is the same
    problem: start work somewhere else, find out later how it went. What
    differs is that this one returns a branch rather than a verdict, which the
    implementation phase then has to review.
    """

    def __init__(
        self,
        repo: str,
        token: str,
        *,
        base_ref: str = "main",
        model: str | None = None,
        custom_agent: str | None = None,
    ) -> None:
        self._repo = repo
        self._token = token
        self._base_ref = base_ref
        self._model = model
        self._custom_agent = custom_agent

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    async def trigger(
        self, run_id: str, phase: str, correlation_id: str, inputs: dict[str, Any]
    ) -> DispatchHandle:
        prompt = inputs.get("prompt") or ""
        if not prompt.strip():
            raise ValueError(
                "refusing to start a coding agent with no task description — "
                "the design phase produces it and something has dropped it"
            )

        body: dict[str, Any] = {
            "prompt": prompt,
            # A branch and a pull request, so what the agent did is reviewable
            # before it is anywhere near the default branch.
            "create_pull_request": True,
            "base_ref": inputs.get("base_ref") or self._base_ref,
        }
        if self._model:
            body["model"] = self._model
        if self._custom_agent:
            body["custom_agent"] = self._custom_agent

        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.post(
                f"{_API}/agents/repos/{self._repo}/tasks",
                headers=self._headers,
                json=body,
            )
            _raise_for_status(response, f"starting a Copilot task on {self._repo}")
            task = response.json()

        return DispatchHandle(
            provider="github-copilot",
            correlation_id=correlation_id,
            external_id=str(task.get("id") or ""),
            external_url=task.get("html_url"),
        )

    async def check_access(self) -> dict[str, Any]:
        """Can this token start tasks on this repository?

        Read-only on purpose. Listing tasks exercises exactly the auth and
        the entitlement that starting one needs, without starting one —
        a connection test that costs a real agent run and opens a real pull
        request is not a connection test.
        """
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.get(
                f"{_API}/agents/repos/{self._repo}/tasks",
                headers=self._headers,
                params={"per_page": 1},
            )

        if response.status_code == 200:
            tasks = (response.json() or {}).get("tasks") or []
            return {
                "ok": True,
                "detail": (
                    f"Copilot cloud agent is reachable on {self._repo}"
                    + (f"; {len(tasks)} recent task(s)" if tasks else "; no tasks yet")
                ),
            }
        if response.status_code in (401, 403):
            return {
                "ok": False,
                "detail": (
                    f"{response.status_code}: the token is not authorised for the Copilot "
                    f"cloud agent on {self._repo}. It needs Copilot access as well as "
                    f"repository access, and the agent must be enabled for the repository."
                ),
            }
        if response.status_code == 404:
            return {
                "ok": False,
                "detail": (
                    f"{self._repo} was not found. Check the owner/name, and note that a "
                    f"private repository needs a token that can see it."
                ),
            }
        return {"ok": False, "detail": f"{response.status_code}: {response.text[:200]}"}

    async def check(self, handle: DispatchHandle) -> DispatchResult:
        if not handle.external_id:
            # Unlike workflow_dispatch there is no correlation search to fall
            # back on: the POST returns the id, so its absence means the
            # trigger did not complete.
            return DispatchResult(
                state="failed", detail="the task was never started — no task id was recorded"
            )

        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.get(
                f"{_API}/agents/repos/{self._repo}/tasks/{handle.external_id}",
                headers=self._headers,
            )
            if response.status_code == 404:
                return DispatchResult(
                    state="failed",
                    detail=f"task {handle.external_id} no longer exists",
                    external_id=handle.external_id,
                )
            _raise_for_status(response, f"checking Copilot task {handle.external_id}")
            task = response.json()

        return _result_from(task, handle)


def _result_from(task: dict[str, Any], handle: DispatchHandle) -> DispatchResult:
    state = str(task.get("state") or "").lower()
    artifacts = artifacts_of(task)
    common = {
        "external_id": handle.external_id,
        "external_url": task.get("html_url") or handle.external_url,
    }

    if state in _PENDING:
        return DispatchResult(
            state="pending",
            detail=(
                "the agent is waiting for input in GitHub"
                if state in ("idle", "waiting_for_user")
                else f"agent {state}"
            ),
            **common,
        )
    if state == "timed_out":
        return DispatchResult(state="timed_out", detail="the agent timed out", **common)
    if state in _FAILED:
        return DispatchResult(state="failed", detail=f"the agent {state}", **common)

    if state == "completed":
        if not artifacts.get("head_ref"):
            # A completed task that produced no branch has nothing to review.
            # Treating it as success would send an empty change to QA.
            return DispatchResult(
                state="failed",
                detail="the agent finished without producing a branch",
                **common,
            )
        return DispatchResult(state="succeeded", payload=artifacts, **common)

    return DispatchResult(state="failed", detail=f"unrecognised task state {state!r}", **common)


def artifacts_of(task: dict[str, Any]) -> dict[str, Any]:
    """The branch and pull request the task produced, if any.

    Artifacts are a list of typed resources rather than named fields, so this
    picks out the two that matter and leaves the rest. A task can report a
    branch before it reports a pull request.
    """
    out: dict[str, Any] = {}
    for artifact in task.get("artifacts") or []:
        data = artifact.get("data") or {}
        if artifact.get("type") == "branch":
            out.setdefault("head_ref", data.get("head_ref"))
            out.setdefault("base_ref", data.get("base_ref"))
        elif artifact.get("type") == "pull":
            out.setdefault("pull_request_id", data.get("id"))
            out.setdefault("pull_request_global_id", data.get("global_id"))
    return {k: v for k, v in out.items() if v is not None}


def _raise_for_status(response: httpx.Response, doing: str) -> None:
    if response.status_code < 400:
        return
    detail = response.text[:300]
    if response.status_code in (401, 403):
        raise ValueError(
            f"{doing}: {response.status_code}. The token needs Copilot cloud agent "
            f"access on this repository. {detail}"
        )
    raise ValueError(f"{doing}: {response.status_code} {detail}")
