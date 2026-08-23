"""Demo-default CodeDesignContext adapter.

This is explicitly a PLACEHOLDER: it scores similarity with stdlib
`difflib.SequenceMatcher` over two tiny fixture docs, not a real embedding
pipeline. Indexing the real `demo-app/` content into a vector index is a
later phase — this adapter exists only to prove the interface boundary.
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
