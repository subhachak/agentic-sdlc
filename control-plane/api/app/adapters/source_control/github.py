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

    async def _compare(self, repo: str, base_ref: str, head_ref: str) -> list[dict]:
        """The raw file list for a revision pair.

        Shared by change_files and changed_paths so the two cannot end up
        describing different comparisons of the same pair.
        """
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(
                f"{_API}/repos/{repo}/compare/{base_ref}...{head_ref}",
                headers=self._headers,
                params={"per_page": 300},
            )
            if resp.status_code != 200:
                raise ValueError(
                    f"could not compare {base_ref}...{head_ref} on {repo}: "
                    f"{resp.status_code} {resp.text[:200]}"
                )
        listed = resp.json().get("files") or []
        # The compare endpoint paginates at 300 files, so a larger change is
        # refused rather than silently described in part. The difference
        # between "25 files" and "a truncated view of 4000" must never be
        # invisible — a partial file list produces a narrow blast radius that
        # looks exactly like a small change.
        if len(listed) >= 300:
            raise ValueError(
                f"{base_ref}...{head_ref} changes at least {len(listed)} files, more than "
                f"one compare page — refusing to describe a partial view of it"
            )
        return listed

    async def changed_paths(self, repo: str, base_ref: str, head_ref: str) -> list[str]:
        """Every path the pair touched, deletions included.

        `previous_filename` is carried for a rename so the path that no
        longer exists is still in scope: its dependents are exactly what a
        rename can break.
        """
        paths: set[str] = set()
        for entry in await self._compare(repo, base_ref, head_ref):
            if entry.get("filename"):
                paths.add(entry["filename"])
            if entry.get("previous_filename"):
                paths.add(entry["previous_filename"])
        return sorted(paths)

    async def change_files(self, repo: str, base_ref: str, head_ref: str) -> list[FileEdit]:
        """What a branch changed, read back from the repository.

        Used to review a change this platform did not write — a cloud coding
        agent opens its own branch, so containment is checked against what it
        did rather than against what it said it would do.

        The compare endpoint paginates at 300 files and reports the total, so
        a change larger than that is refused here rather than silently
        reviewed in part. The change review has its own, much smaller limit;
        this one exists so the difference between "25 files" and "a truncated
        view of 4000" is never invisible.
        """
        listed = await self._compare(repo, base_ref, head_ref)

        wanted = [
            f["filename"]
            for f in listed
            # A deleted file has no content at head to review; a module losing
            # a file is caught by the path check instead.
            if f.get("status") != "removed"
        ]
        contents = await self.read_files(repo, head_ref, wanted)
        return [
            FileEdit(path=path, content=contents[path]) for path in wanted if path in contents
        ]

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
