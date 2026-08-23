"""Index a directory on disk.

Exists so the seeder can be demonstrated and tested with no network, and so
a client whose code is not on GitHub can still index a checkout.
"""

from __future__ import annotations

from pathlib import Path

from app.adapters.code_intelligence.github import _index_from_sources
from app.adapters.code_intelligence.parsing import is_ignored, is_source
from app.ports.code_intelligence import CodeIndex

MAX_FILE_BYTES = 400_000
MAX_FILES = 4000


class LocalPathCodeIntelligence:
    def __init__(self, root: Path, max_depth: int = 4) -> None:
        self._root = Path(root)
        self._max_depth = max_depth

    async def index(self, repo: str, ref: str = "local") -> CodeIndex:
        base = self._root / repo if repo and (self._root / repo).exists() else self._root
        if not base.exists():
            raise ValueError(f"{base} does not exist")

        sources: dict[str, str] = {}
        skipped = 0
        tsconfig: str | None = None

        for path in sorted(base.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(base).as_posix()
            if is_ignored(rel):
                continue
            if rel.endswith("tsconfig.json") and tsconfig is None:
                tsconfig = path.read_text(encoding="utf-8", errors="replace")
                continue
            if not is_source(rel):
                continue
            if path.stat().st_size > MAX_FILE_BYTES or len(sources) >= MAX_FILES:
                skipped += 1
                continue
            sources[rel] = path.read_text(encoding="utf-8", errors="replace")

        return _index_from_sources(
            str(base), ref, sources, skipped, tsconfig, self._max_depth
        )
