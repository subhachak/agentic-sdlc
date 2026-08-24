"""Propose a change as a branch and a pull request on GitHub.

Uses the Git Data API rather than one Contents call per file, so a
multi-file change lands as a single commit — which is what makes the diff
reviewable and the change revertible as one thing.

It opens a pull request and stops. Merging is somebody else's decision, and
in a client's repository it is their existing review process.
"""

from __future__ import annotations

import base64

import httpx

from app.ports.source_control import ChangeRef, FileEdit

_API = "https://api.github.com"
_TIMEOUT = 60.0


class GitHubSourceControl:
    def __init__(self, token: str) -> None:
        self._token = token

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    async def read_files(self, repo: str, ref: str, paths: list[str]) -> dict[str, str]:
        out: dict[str, str] = {}
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            for path in paths:
                resp = await client.get(
                    f"{_API}/repos/{repo}/contents/{path}",
                    headers=self._headers,
                    params={"ref": ref},
                )
                if resp.status_code != 200:
                    continue
                payload = resp.json()
                if payload.get("encoding") == "base64":
                    out[path] = base64.b64decode(payload["content"]).decode(
                        "utf-8", "replace"
                    )
        return out

    async def open_change(
        self, repo, base_ref, branch, title, body, edits: list[FileEdit]
    ) -> ChangeRef:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:

            async def call(method: str, path: str, **kwargs):
                resp = await client.request(
                    method, f"{_API}/repos/{repo}{path}", headers=self._headers, **kwargs
                )
                resp.raise_for_status()
                return resp.json()

            base = await call("GET", f"/git/ref/heads/{base_ref}")
            base_sha = base["object"]["sha"]
            base_commit = await call("GET", f"/git/commits/{base_sha}")

            tree = await call(
                "POST",
                "/git/trees",
                json={
                    "base_tree": base_commit["tree"]["sha"],
                    "tree": [
                        {
                            "path": edit.path,
                            "mode": "100644",
                            "type": "blob",
                            "content": edit.content,
                        }
                        for edit in edits
                    ],
                },
            )
            commit = await call(
                "POST",
                "/git/commits",
                json={
                    "message": f"{title}\n\n{body}",
                    "tree": tree["sha"],
                    "parents": [base_sha],
                },
            )
            await call(
                "POST", "/git/refs", json={"ref": f"refs/heads/{branch}", "sha": commit["sha"]}
            )
            pull = await call(
                "POST",
                "/pulls",
                json={"title": title, "body": body, "head": branch, "base": base_ref},
            )

        return ChangeRef(
            provider="github",
            branch=branch,
            url=pull["html_url"],
            number=pull["number"],
            commit=commit["sha"],
            # The revision the branch was cut from. A QA run downstream diffs
            # against this; without it there is no pair to scope between.
            base_commit=base_sha,
            files=[e.path for e in edits],
        )
