"""Port: grounds the Design Agent against an existing system.

Default adapter: lexical retrieval over the repository the context graph
currently holds, chunked per top-level definition. Future: an embedding index
where a client wants prose recall over design documents as well as code.

Scores are relative to one query over one corpus. Nothing downstream may read
them as a confidence, and nothing is gated on them — retrieval changes what
an agent proposes, and the deterministic reviews decide what survives.
"""

from typing import Protocol

from pydantic import BaseModel


class ContextSnippet(BaseModel):
    doc_id: str
    title: str
    text: str
    score: float


class CodeDesignContext(Protocol):
    async def retrieve_context(self, query: str, top_k: int = 8) -> list[ContextSnippet]: ...
