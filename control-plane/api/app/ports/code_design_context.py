"""Port: grounds the Design Agent against an existing system.

Demo adapter: a placeholder similarity index over a stub doc (indexing the
real `demo-app/` is a later phase). Future: Git repo index, Confluence docs.
"""

from typing import Protocol

from pydantic import BaseModel


class ContextSnippet(BaseModel):
    doc_id: str
    title: str
    text: str
    score: float


class CodeDesignContext(Protocol):
    async def retrieve_context(self, query: str, top_k: int = 3) -> list[ContextSnippet]: ...
