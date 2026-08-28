"""Deploy by merging, observe by asking GitHub, reverse by reverting.

The platform does not call a hosting API to deploy. Gate 3 approval merges
the pull request, and the client's existing automation — Vercel for the web
app, Railway for the API — reacts to that merge exactly as it reacts to a
human's. The platform drives the pipeline through the same door a person
would, then observes what happened.

That is a governance position, not a shortcut. Nothing routes around the
client's CI or their branch protections, so the demo shows the controls
working rather than replacing them. A platform that deploys by its own path
proves only that its own path works.

Three consequences worth stating, because each one is a choice:

  Health is unknown at merge time. `deploy` reports `healthy=None` rather
  than True — the merge mechanism succeeded, and whether the thing works is
  a question only `check` can answer, minutes later. The port allows None
  precisely so an adapter need not pretend.

  Observation goes through GitHub, not Vercel. Vercel and Railway both post
  GitHub Deployment statuses against the merge commit, so one credential
  reads both. A second integration would mean a second token, a second API
  that can change underneath us, and an adapter that reports on one host
  while the other is unobserved.

  Rollback is `git revert`, not a hosting call. There is no REST endpoint to
  revert a merged pull request — the reverse diff of a merge commit is not
  something the Git Data API can compute — so this shells out to git in a
  working copy. That is also the better answer: if a merge deploys, a revert
  deploys too, and the repository and the running system never disagree.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import httpx

from app.ports.build_deploy import (
    Artifact,
    DeployOutcome,
    Deployment,
    DeployRequest,
)

_API = "https://api.github.com"
_TIMEOUT = 30.0

# GitHub deployment status states, mapped to the only question a release gate
# asks. `inactive` is absent deliberately: it means superseded, which says
# nothing about whether this deployment ever worked.
_HEALTHY = {"success"}
_UNHEALTHY = {"failure", "error"}
_IN_FLIGHT = {"pending", "queued", "in_progress", "waiting"}


class GitHubMergeDeploy:
    """BuildDeploy over "merge the approved pull request".

    `deployment_id` throughout is the **merge commit sha**. It is the only
    identifier that survives all three operations: it is what the merge
    returns, what hosting platforms attach their deployment statuses to, and
    what a revert has to name. A GitHub deployment id would be none of those
    — there can be several per commit, one per host.
    """

    def __init__(
        self,
        repo: str,
        token: str,
        *,
        base_ref: str = "main",
        merge_method: str = "merge",
        working_copy: Path | None = None,
    ) -> None:
        self._repo = repo
        self._token = token
        self._base_ref = base_ref
        self._merge_method = merge_method
        self._working_copy = Path(working_copy) if working_copy else None

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    # --- deploy ----------------------------------------------------------

    async def deploy(self, request: DeployRequest) -> DeployOutcome:
        if not request.branch:
            # Without a branch there is no pull request to merge. Refusing
            # beats merging something chosen by default, which at this point
            # in the pipeline would ship code no gate approved.
            return DeployOutcome(
                state="failed",
                detail="the implementation phase recorded no branch, so there is nothing to merge",
            )

        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            number = await self._pull_for(client, request.branch)
            if number is None:
                return DeployOutcome(
                    state="failed",
                    detail=(
                        f"no open pull request for {request.branch}. The change may "
                        f"already be merged, or the agent never opened one."
                    ),
                )

            body: dict[str, Any] = {"merge_method": self._merge_method}
            # Merge only the revision the gates actually approved. Without
            # this a commit pushed between approval and release is merged
            # too, and the audit trail names a revision nobody reviewed.
            if request.revision:
                body["sha"] = request.revision

            response = await client.put(
                f"{_API}/repos/{self._repo}/pulls/{number}/merge",
                headers=self._headers,
                json=body,
            )

        if response.status_code == 405:
            return DeployOutcome(
                state="failed",
                detail=f"pull request #{number} is not mergeable: {_message(response)}",
            )
        if response.status_code == 409:
            # The head moved, or someone merged it first. Both mean the thing
            # approved is not the thing that would ship.
            return DeployOutcome(
                state="failed",
                detail=(
                    f"pull request #{number} changed since it was approved "
                    f"({_message(response)}); it was not merged"
                ),
            )
        if response.status_code >= 400:
            return DeployOutcome(
                state="failed",
                detail=f"merging #{number} failed: {response.status_code} {_message(response)}",
            )

        merged = response.json()
        sha = str(merged.get("sha") or "")
        if not merged.get("merged") or not sha:
            return DeployOutcome(
                state="failed",
                detail=f"GitHub did not confirm the merge: {merged.get('message') or '?'}",
            )

        return DeployOutcome(
            state="ready",
            deployment=Deployment(
                deployment_id=sha,
                environment=request.environment,
                artifact=Artifact(
                    kind="commit",
                    reference=f"{self._repo}@{sha}",
                    # The merge commit *is* the content identity here. There
                    # is no registry digest, because nothing built an image —
                    # the client's own automation will.
                    digest=sha,
                    build_id=str(number),
                ),
                revision=sha,
                url=merged.get("html_url") or f"https://github.com/{self._repo}/commit/{sha}",
                succeeded=True,
                # Not False. The merge worked; whether the deployment it
                # triggers is healthy is unknowable for another few minutes,
                # and a release gate reading False would be acting on a check
                # nobody has run yet. `check` answers this.
                healthy=None,
                detail=f"merged #{number} as {sha[:8]}; the client's automation deploys from here",
            ),
        )

    async def _pull_for(self, client: httpx.AsyncClient, branch: str) -> int | None:
        """The open pull request for a branch.

        Looked up rather than carried on the request. The two agent shapes
        produce it differently — the inline agent opens the pull request, a
        cloud agent opens its own — and asking the repository is the one
        answer that is true for both.
        """
        owner = self._repo.split("/")[0]
        response = await client.get(
            f"{_API}/repos/{self._repo}/pulls",
            headers=self._headers,
            params={"head": f"{owner}:{branch}", "state": "open", "per_page": 1},
        )
        response.raise_for_status()
        pulls = response.json() or []
        return int(pulls[0]["number"]) if pulls else None

    # --- observe ---------------------------------------------------------

    async def check(self, handle: str) -> DeployOutcome:
        """What the client's automation did with that merge commit.

        Reads GitHub Deployment statuses rather than any host's own API, so
        one credential covers every platform that reports back — and a host
        that reports nothing is visibly unobserved rather than silently
        assumed healthy.
        """
        if not handle:
            return DeployOutcome(state="failed", detail="no merge commit to check")

        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.get(
                f"{_API}/repos/{self._repo}/deployments",
                headers=self._headers,
                params={"sha": handle, "per_page": 50},
            )
            response.raise_for_status()
            deployments = response.json() or []

            if not deployments:
                # No host has claimed this commit. Pending rather than
                # healthy: automation that has not started is not automation
                # that succeeded, and the deadline is what decides.
                return DeployOutcome(
                    state="pending",
                    handle=handle,
                    detail=(
                        "no deployment has been created for this commit yet — the "
                        "client's automation may not have picked it up"
                    ),
                )

            states: list[tuple[str, str, str]] = []
            for deployment in deployments:
                statuses = await client.get(
                    f"{_API}/repos/{self._repo}/deployments/{deployment['id']}/statuses",
                    headers=self._headers,
                    params={"per_page": 1},
                )
                statuses.raise_for_status()
                latest = (statuses.json() or [{}])[0]
                states.append(
                    (
                        str(deployment.get("environment") or "?"),
                        str(latest.get("state") or "pending"),
                        str(latest.get("target_url") or deployment.get("url") or ""),
                    )
                )

        summary = ", ".join(f"{env}: {state}" for env, state, _ in states)
        url = next((u for _, _, u in states if u), "")

        # Every host has to be healthy. One green and one red is not a
        # healthy release — it is half a release, which is the state a
        # rollback exists for.
        if any(state in _UNHEALTHY for _, state, _ in states):
            healthy: bool | None = False
        elif any(state in _IN_FLIGHT for _, state, _ in states):
            return DeployOutcome(
                state="pending", handle=handle, detail=f"still deploying — {summary}"
            )
        elif all(state in _HEALTHY for _, state, _ in states):
            healthy = True
        else:
            # A state nothing here recognises. Unknown, never assumed good.
            healthy = None

        return DeployOutcome(
            state="ready",
            deployment=Deployment(
                deployment_id=handle,
                environment=states[0][0] if states else "",
                artifact=Artifact(kind="commit", reference=f"{self._repo}@{handle}", digest=handle),
                revision=handle,
                url=url,
                succeeded=True,
                healthy=healthy,
                detail=summary,
            ),
        )

    # --- reverse ---------------------------------------------------------

    async def rollback(self, deployment_id: str) -> DeployOutcome:
        """Revert the merge commit and push, so the way back is the way in.

        Deliberately the same mechanism as the deploy, backwards: the revert
        lands on the default branch, the client's automation redeploys from
        it, and both hosts return together. A hosting-level re-promote would
        leave the repository claiming something the running system no longer
        does.
        """
        if self._working_copy is None:
            return DeployOutcome(
                state="failed",
                detail=(
                    "rollback needs a working copy to revert in — set "
                    "TARGET_WORKING_COPY to a checkout that can push to "
                    f"{self._repo}"
                ),
            )
        if not deployment_id:
            return DeployOutcome(state="failed", detail="no merge commit to revert")

        try:
            self._git("fetch", "origin", self._base_ref)
            self._git("checkout", self._base_ref)
            self._git("reset", "--hard", f"origin/{self._base_ref}")

            # `-m 1` names the mainline parent and is required for a merge
            # commit — and rejected for an ordinary one. Which this is depends
            # on the merge method: `squash` and `rebase` produce a single
            # parent, `merge` produces two. Asking the commit is the only
            # answer that survives someone changing MERGE_METHOD.
            parents = self._git("rev-list", "--parents", "-n", "1", deployment_id).split()
            revert = ["revert", "--no-edit"]
            if len(parents) > 2:  # the commit itself plus two or more parents
                revert += ["-m", "1"]
            self._git(*revert, deployment_id)

            reverted = self._git("rev-parse", "HEAD")
            self._git("push", "origin", self._base_ref)
        except RuntimeError as exc:
            # Left where it is on purpose. A half-finished revert is a state
            # a person needs to see, and a cleanup that silently discards it
            # would also discard the evidence of why it failed.
            return DeployOutcome(state="failed", detail=f"the revert did not complete: {exc}")

        return DeployOutcome(
            state="ready",
            deployment=Deployment(
                deployment_id=reverted,
                environment="",
                artifact=Artifact(
                    kind="commit", reference=f"{self._repo}@{reverted}", digest=reverted
                ),
                revision=reverted,
                url=f"https://github.com/{self._repo}/commit/{reverted}",
                succeeded=True,
                # Same reasoning as the deploy: the revert is pushed, the
                # redeploy it triggers has not finished. `check` answers it.
                healthy=None,
                detail=f"reverted {deployment_id[:8]} as {reverted[:8]} on {self._base_ref}",
            ),
        )

    def _git(self, *args: str) -> str:
        result = subprocess.run(
            ["git", *args], cwd=self._working_copy, capture_output=True, text=True
        )
        if result.returncode != 0:
            raise RuntimeError(f"git {' '.join(args)}: {result.stderr.strip()}")
        return result.stdout.strip()

    async def check_access(self) -> dict[str, Any]:
        """Can this token merge on this repository?

        Read-only: reads the repository's own permissions rather than
        attempting a merge. A connection test that ships code is not a
        connection test.
        """
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.get(
                f"{_API}/repos/{self._repo}", headers=self._headers
            )

        if response.status_code == 404:
            return {
                "ok": False,
                "detail": f"{self._repo} was not found, or the token cannot see it",
            }
        if response.status_code >= 400:
            return {"ok": False, "detail": f"{response.status_code}: {_message(response)}"}

        permissions = (response.json() or {}).get("permissions") or {}
        if not permissions.get("push"):
            return {
                "ok": False,
                "detail": (
                    f"the token can read {self._repo} but not push to it, so it "
                    f"cannot merge a pull request or push a revert"
                ),
            }
        note = "" if self._working_copy else "; no working copy configured, so rollback is unavailable"
        return {"ok": True, "detail": f"can merge and push on {self._repo}{note}"}


def _message(response: httpx.Response) -> str:
    try:
        return str((response.json() or {}).get("message") or response.text[:200])
    except ValueError:
        return response.text[:200]
