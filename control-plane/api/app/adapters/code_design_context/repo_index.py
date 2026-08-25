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
        # How the last build went. An index over zero files answers every
        # question with nothing and looks identical to a question with no
        # good answer, so the build has to be able to say it read nothing.
        self._last_read: dict[str, Any] = {}

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
        failures: list[str] = []
        for start in range(0, len(paths), BATCH):
            batch = paths[start : start + BATCH]
            try:
                sources.update(
                    await self._source_control.read_files(self._repo, self._ref, batch)
                )
            except Exception as exc:  # noqa: BLE001
                # A file the graph knows about that source control will not
                # return is a stale-graph symptom, not a reason to leave the
                # agent with no grounding at all — so the build continues.
                #
                # But it is recorded. Swallowing these silently is how the
                # graph came to be indexed from one repository while
                # retrieval read a different one, and the console reported
                # the index as built.
                failures.append(f"{type(exc).__name__}: {exc}")
                continue

        self._last_read = {
            "requested": len(paths),
            "read": len(sources),
            "missing": len(paths) - len(sources),
            "batch_errors": failures[:3],
        }
        return sources

    async def status(self) -> dict[str, Any]:
        """Whether the design agent has anything to be grounded in.

        Reported rather than inferred from a successful query: an index built
        over zero files answers every question with nothing, which looks
        exactly like a question with no good answer.
        """
        provenance = await self._graph.index_provenance()
        read = self._last_read
        requested = read.get("requested", 0)
        empty = self._index is not None and not len(self._index)
        return {
            "built": self._index is not None,
            "chunks": len(self._index) if self._index is not None else 0,
            "files_requested": requested,
            "files_read": read.get("read", 0),
            # The useful message, not the count. "0 chunks" reads as "small
            # repository"; this reads as the configuration mistake it is.
            "problem": (
                f"read 0 of {requested} files from {self._repo or 'an unnamed repository'!r} "
                f"at {self._ref!r} — the graph is indexed from one place and grounding "
                f"is reading another"
                if empty and requested
                else None
            ),
            "batch_errors": read.get("batch_errors", []),
            "built_for": self._built_for,
            "current_commit": provenance.get("commit_sha"),
            "stale": self._index is not None
            and self._built_for != (provenance.get("commit_sha") or f"unpinned:{self._ref}"),
            "repo": self._repo,
            "ref": self._ref,
        }

    async def rebuild(self) -> dict[str, Any]:
        """Discard the index and build it again.

        Exists so first-time setup is a thing someone can do and watch,
        rather than something that happens invisibly on whichever request
        happens to be first.
        """
        async with self._lock:
            self._index = None
            self._built_for = None
        await self._ensure_index()
        return await self.status()
