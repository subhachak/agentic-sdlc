"""Ground the design agent in the repository it is designing against.

Replaces a placeholder that scored `difflib` similarity over two fixture
documents totalling seventeen lines — which meant the architecture phase had
never seen a line of the codebase it was naming modules from.

The file list comes from the context graph rather than from a directory walk.
That is deliberate: retrieval must be reading the same snapshot that impact
and containment read, or an agent can be shown code that the graph does not
believe exists. The content comes through the SourceControl port, so this
adapter works against whatever the client's code actually lives in.
"""

from __future__ import annotations

import asyncio
from typing import Any

from app.core.retrieval import ChunkIndex
from app.ports.code_design_context import ContextSnippet

# Read in batches so a large repository does not become one enormous request
# to whatever the source-control adapter talks to.
BATCH = 200


class IndexedRepoCodeDesignContext:
    """Lexical retrieval over the indexed repository.

    The index is built on first use and reused until the graph reports a
    different commit. Rebuilding on a changed commit rather than on a timer is
    what keeps the answer reproducible: the same question against the same
    snapshot returns the same excerpts.
    """

    def __init__(self, graph: Any, source_control: Any, repo: str, ref: str = "main") -> None:
        self._graph = graph
        self._source_control = source_control
        self._repo = repo
        self._ref = ref
        self._index: ChunkIndex | None = None
        self._built_for: str | None = None
        self._lock = asyncio.Lock()

    async def retrieve_context(self, query: str, top_k: int = 8) -> list[ContextSnippet]:
        index = await self._ensure_index()
        if index is None or not len(index):
            return []

        return [
            ContextSnippet(
                doc_id=chunk.id,
                title=chunk.title,
                text=chunk.text,
                score=score,
            )
            for chunk, score in index.search(query, top_k)
        ]

    async def _ensure_index(self) -> ChunkIndex | None:
        provenance = await self._graph.index_provenance()
        # An unpinned graph has no stable identity to cache against, so fall
        # back to the ref and accept that a rebuild may be missed. Saying so
        # here is better than pretending the snapshot is fixed.
        key = provenance.get("commit_sha") or f"unpinned:{self._ref}"

        async with self._lock:
            if self._index is not None and self._built_for == key:
                return self._index

            sources = await self._read_sources()
            self._index = ChunkIndex.build(sources)
            self._built_for = key
            return self._index

    async def _read_sources(self) -> dict[str, str]:
        paths = sorted(
            {path for paths in (await self._graph.module_paths()).values() for path in paths}
        )
        sources: dict[str, str] = {}
        for start in range(0, len(paths), BATCH):
            batch = paths[start : start + BATCH]
            try:
                sources.update(
                    await self._source_control.read_files(self._repo, self._ref, batch)
                )
            except Exception:
                # A file the graph knows about that source control will not
                # return is a stale-graph symptom, not a reason to leave the
                # agent with no grounding at all.
                continue
        return sources
