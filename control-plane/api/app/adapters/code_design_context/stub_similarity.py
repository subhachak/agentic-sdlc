"""Fallback CodeDesignContext adapter, kept for the no-source case.

Scores `difflib.SequenceMatcher` similarity over two fixture documents. It
was the default until the design agent was grounded in the actual indexed
repository — see `repo_index.py`, which is what `code_design_context_adapter`
selects unless it is set to "stub".

Retained because it needs no repository, no graph and no source control, so a
test or a bare demo can exercise the port without any of them.
"""

from difflib import SequenceMatcher
from pathlib import Path

from app.ports.code_design_context import ContextSnippet

FIXTURES_DIR = Path(__file__).parent / "fixtures"


class StubSimilarityCodeDesignContext:
    def __init__(self) -> None:
        self._docs = [
            {"doc_id": p.stem, "title": p.stem.replace("_", " ").title(), "text": p.read_text()}
            for p in sorted(FIXTURES_DIR.glob("*.md"))
        ]

    async def retrieve_context(self, query: str, top_k: int = 3) -> list[ContextSnippet]:
        scored = [
            ContextSnippet(
                doc_id=doc["doc_id"],
                title=doc["title"],
                text=doc["text"],
                score=SequenceMatcher(None, query.lower(), doc["text"].lower()).ratio(),
            )
            for doc in self._docs
        ]
        scored.sort(key=lambda s: s.score, reverse=True)
        return scored[:top_k]
