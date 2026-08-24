"""Port: derive a module and dependency graph from a repository.

This is the third of the three graphs — derived, rebuildable, approximate.
Unlike the traceability graph it is regenerated rather than accumulated, so
getting it wrong costs a re-index rather than an audit gap.

Demo adapters: GitHub (fetch an archive and parse it) and a local path.
Future: GitLab, Bitbucket, or a language server for real symbol resolution.
"""

from typing import Protocol

from pydantic import BaseModel, Field


class CodeFile(BaseModel):
    path: str
    module: str


class CodeModule(BaseModel):
    id: str
    paths: list[str] = Field(default_factory=list)
    owners: list[str] = Field(default_factory=list)


class CodeDependency(BaseModel):
    source: str
    target: str
    # How many distinct imports produced this edge — a one-import dependency
    # and a forty-import dependency are not the same claim.
    weight: int = 1


class FileImport(BaseModel):
    source: str
    target: str


class CodeIndex(BaseModel):
    repo: str
    ref: str
    modules: list[CodeModule] = Field(default_factory=list)
    files: list[CodeFile] = Field(default_factory=list)
    dependencies: list[CodeDependency] = Field(default_factory=list)
    imports: list[FileImport] = Field(default_factory=list)
    unresolved_imports: int = 0
    skipped_files: int = 0


class CodeIntelligence(Protocol):
    async def index(self, repo: str, ref: str = "main") -> CodeIndex: ...
