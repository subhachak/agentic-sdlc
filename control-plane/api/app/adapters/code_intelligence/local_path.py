"""Index a directory on disk.

Exists so the seeder can be demonstrated and tested with no network, and so
a client whose code is not on GitHub can still index a checkout.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from app.adapters.code_intelligence.github import _index_from_sources
from app.adapters.code_intelligence.parsing import is_ignored, is_source
from app.core.scoping import is_marker
from app.ports.code_intelligence import CodeIndex, Repository

MAX_FILE_BYTES = 400_000
MAX_FILES = 4000


class LocalPathCodeIntelligence:
    def __init__(self, root: Path, max_depth: int = 4) -> None:
        self._root = Path(root)
        self._max_depth = max_depth

    async def repositories(self) -> list[Repository]:
        """The configured root, named by what it actually is.

        A single entry rather than an empty list: the console's job is to
        stop someone typing a name, and there is exactly one thing this
        adapter can index. `ref` reports the checked-out branch so the same
        UI shows a real value here as it does for GitHub.
        """
        return [
            Repository(
                full_name=self._root.resolve().name,
                default_branch=self._current_branch() or "local",
                private=True,
                description=f"local checkout at {self._root.resolve()}",
            )
        ]

    def _current_branch(self) -> str:
        try:
            out = subprocess.run(
                ["git", "-C", str(self._root), "rev-parse", "--abbrev-ref", "HEAD"],
                capture_output=True, text=True, timeout=5,
            )
            return out.stdout.strip() if out.returncode == 0 else ""
        except (OSError, subprocess.SubprocessError):
            # Not a checkout, or no git. Neither is an error worth raising
            # for a label.
            return ""

    async def index(self, repo: str, ref: str = "local") -> CodeIndex:
        base = self._root / repo if repo and (self._root / repo).exists() else self._root
        if not base.exists():
            raise ValueError(f"{base} does not exist")

        sources: dict[str, str] = {}
        skipped = 0
        tsconfigs: dict[str, str] = {}
        units: set[str] = set()

        for path in sorted(base.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(base).as_posix()
            if is_ignored(rel):
                continue
            # Before the source filter drops it — see the GitHub adapter.
            if is_marker(rel.rsplit("/", 1)[-1]):
                units.add(rel.rsplit("/", 1)[0] if "/" in rel else "")
            # Every config, not the first: a monorepo has one per package.
            if rel.endswith(("tsconfig.json", "jsconfig.json")):
                tsconfigs[rel] = path.read_text(encoding="utf-8", errors="replace")
                continue
            if not is_source(rel):
                continue
            if path.stat().st_size > MAX_FILE_BYTES or len(sources) >= MAX_FILES:
                skipped += 1
                continue
            sources[rel] = path.read_text(encoding="utf-8", errors="replace")

        return _index_from_sources(
            _repo_identity(base), ref, sources, skipped, tsconfigs,
            self._max_depth, _head_sha(base), units=sorted(units),
        )


def _head_sha(base: Path) -> str | None:
    """The commit the working copy is on.

    Exact here, unlike the archive case, because the repository is right
    there. A dirty tree still reports its HEAD — the index describes what was
    read, and uncommitted edits make it unpinnable rather than wrong, which is
    a distinction the seeder surfaces rather than resolves.
    """
    sha = _git(base, "rev-parse", "HEAD")
    return sha if sha and len(sha) == 40 else None


def _repo_identity(base: Path) -> str:
    """What to call this repository in the graph.

    The same repository indexed from a checkout and from a GitHub archive
    must land on one identity, or the two indexes are two graphs. The remote
    slug is what the GitHub adapter uses, so prefer it and fall back to the
    directory name rather than to a relative path nobody can resolve later.
    """
    url = _git(base, "config", "--get", "remote.origin.url")
    if url:
        slug = url.removesuffix(".git").replace(":", "/")
        parts = [p for p in slug.split("/") if p]
        if len(parts) >= 2:
            return "/".join(parts[-2:])
    return base.resolve().name


def _git(base: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(base), *args],
            capture_output=True, text=True, timeout=10, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() or None if result.returncode == 0 else None
