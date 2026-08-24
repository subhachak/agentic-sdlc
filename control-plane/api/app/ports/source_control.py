"""Port: read a repository, and propose a change to it.

The implementation phase needs two things from wherever the code lives:
enough of it to write a patch against, and somewhere to put the result. It
deliberately cannot merge — a change is proposed, and what happens to it is
decided by a gate and then by whatever review the client already runs.

Demo adapter: a local working copy, which writes a branch and no pull
request. Real adapter: GitHub. Future: GitLab, Bitbucket, Azure Repos.
"""

from typing import Protocol

from pydantic import BaseModel, Field


class FileEdit(BaseModel):
    path: str
    content: str


class ChangeRef(BaseModel):
    """Where a proposed change ended up."""

    provider: str
    branch: str
    url: str | None = None
    number: int | None = None  # pull request number, where there is one
    commit: str | None = None
    files: list[str] = Field(default_factory=list)


class SourceControl(Protocol):
    async def read_files(
        self, repo: str, ref: str, paths: list[str]
    ) -> dict[str, str]: ...

    async def open_change(
        self,
        repo: str,
        base_ref: str,
        branch: str,
        title: str,
        body: str,
        edits: list[FileEdit],
    ) -> ChangeRef: ...
