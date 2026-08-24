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
    language: str = "unknown"
    # Content identity, so a later index can tell which files actually
    # changed without re-reading the previous snapshot.
    sha256: str = ""
    loc: int = 0
    # The names this file offers its importers. Present so a change can later
    # be classified as touching a public surface or only an internal one.
    exports: list[str] = Field(default_factory=list)


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
    # "runtime" or "type-only". A type-only import is erased at compile time:
    # real coupling for a type checker, none at runtime.
    kind: str = "runtime"
    # Whether the importing file is test code. Kept rather than filtered —
    # regression scoping wants these edges, hub ranking does not.
    from_test: bool = False


class IndexProvenance(BaseModel):
    """What produced this index, and how completely.

    Every number a gate quotes is only as good as the snapshot behind it, so
    the snapshot has to be able to say what it was. An index that cannot name
    its commit cannot be compared with the next one, and an index that hides
    its unresolved imports flatters itself.
    """

    commit_sha: str | None = None
    indexer_version: str = ""
    indexed_at: str = ""
    files_indexed: int = 0
    skipped_files: int = 0
    total_imports: int = 0
    resolved: int = 0
    external_package: int = 0
    unresolved_relative: int = 0
    unresolved_internal: int = 0
    type_only: int = 0
    from_tests: int = 0
    runtime_product: int = 0
    # HTTP coupling. `unmatched_calls` is the honest counterpart to
    # `contract_edges`: a URL assembled at runtime cannot be matched, and the
    # count says how much coupling this still cannot see.
    contract_edges: int = 0
    unmatched_calls: int = 0
    uncalled_routes: int = 0
    # resolved / (resolved + unresolved). The headline completeness number.
    internal_capture_rate: float = 1.0
    most_missed: list[tuple[str, int]] = Field(default_factory=list)


class ContractCall(BaseModel):
    """A file that calls a route, and the file that handles it."""

    source: str
    target: str
    route: str
    method: str = ""
    provenance: str = "static-route-match"


class CodeIndex(BaseModel):
    repo: str
    ref: str
    modules: list[CodeModule] = Field(default_factory=list)
    files: list[CodeFile] = Field(default_factory=list)
    dependencies: list[CodeDependency] = Field(default_factory=list)
    imports: list[FileImport] = Field(default_factory=list)
    contracts: list[ContractCall] = Field(default_factory=list)
    provenance: IndexProvenance = Field(default_factory=IndexProvenance)


class CodeIntelligence(Protocol):
    async def index(self, repo: str, ref: str = "main") -> CodeIndex: ...
