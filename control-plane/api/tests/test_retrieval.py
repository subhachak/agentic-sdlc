"""Retrieval over source code.

Nothing is gated on a retrieval score, so these tests pin usefulness rather
than correctness: does the chunk a question is about come back, and does it
come back above the noise.
"""

from __future__ import annotations

import pytest

from app.core.retrieval import (
    MAX_CHUNK_CHARS,
    ChunkIndex,
    chunk_file,
    is_test_path,
    tokenize,
)
from app.adapters.code_design_context.repo_index import IndexedRepoCodeDesignContext


# --- tokenizing ------------------------------------------------------------


def test_identifiers_split_the_way_they_are_written():
    """A requirement is written in English; the code is not. Unless both
    reduce to the same tokens, retrieval finds nothing."""
    assert tokenize("getClaimStatus") == ["get", "claim", "status"]
    assert tokenize("get_claim_status") == ["get", "claim", "status"]
    assert tokenize("app/claims/StatusFilter.tsx") == [
        "app", "claims", "status", "filter", "tsx",
    ]


def test_acronyms_stay_together_until_a_word_starts():
    assert tokenize("HTTPResponseCode") == ["http", "response", "code"]


def test_single_characters_and_stopwords_are_dropped():
    assert tokenize("a is the x claim") == ["claim"]


# --- chunking --------------------------------------------------------------


PY_SOURCE = '''"""Claims filtering."""

import json

STATUSES = ["open", "closed"]


def filter_claims(claims, status):
    """Return only claims in the given status."""
    return [c for c in claims if c["status"] == status]


class ClaimStore:
    def all(self):
        return []
'''


def test_python_chunks_have_exact_boundaries_from_ast():
    chunks = chunk_file("app/claims.py", PY_SOURCE)
    by_name = {c.name: c for c in chunks}

    assert set(by_name) == {"claims.py", "filter_claims", "ClaimStore"}
    assert by_name["filter_claims"].kind == "symbol"
    assert "def filter_claims" in by_name["filter_claims"].text
    # The boundary is exact, so the next definition does not leak in.
    assert "class ClaimStore" not in by_name["filter_claims"].text


def test_the_file_header_is_its_own_chunk():
    """What a file is *for* lives in its docstring and imports, not in any one
    function inside it."""
    header = next(c for c in chunk_file("app/claims.py", PY_SOURCE) if c.kind == "file")

    assert "Claims filtering" in header.text
    assert "import json" in header.text
    assert "def filter_claims" not in header.text


def test_a_file_that_does_not_parse_still_yields_its_header():
    chunks = chunk_file("app/broken.py", '"""Docs."""\ndef (:\n')
    assert [c.kind for c in chunks] == ["file"]
    assert "Docs." in chunks[0].text


TS_SOURCE = """import { useState } from "react";

export function StatusFilter({ value }) {
  return <select value={value} />;
}

export const DEFAULT_STATUS = "open";
"""


def test_typescript_exports_become_chunks():
    names = {c.name for c in chunk_file("web/filter.tsx", TS_SOURCE)}
    assert {"StatusFilter", "DEFAULT_STATUS"} <= names


def test_an_enormous_chunk_is_clipped_and_says_so():
    chunk = chunk_file("app/big.py", "def f():\n" + "    x = 1\n" * 5000)[-1]
    assert len(chunk.text) <= MAX_CHUNK_CHARS + 32
    assert chunk.text.endswith("(truncated)")


# --- ranking ---------------------------------------------------------------


CORPUS = {
    "app/claims/filters.py": PY_SOURCE,
    "app/billing/invoice.py": '"""Invoice totals."""\n\n\ndef total(lines):\n    return sum(lines)\n',
    "app/util/dates.py": '"""Date helpers."""\n\n\ndef parse(value):\n    return value\n',
}


def test_the_relevant_chunk_ranks_first():
    index = ChunkIndex.build(CORPUS)
    top = index.search("filter claims by status", top_k=3)

    assert top, "expected at least one hit"
    assert top[0][0].path == "app/claims/filters.py"
    assert top[0][1] > 0


def test_a_symbol_name_finds_that_symbol_not_its_neighbours():
    index = ChunkIndex.build(CORPUS)
    best = index.search("filter_claims", top_k=1)[0][0]

    assert best.kind == "symbol"
    assert best.name == "filter_claims"


def test_a_query_matching_nothing_returns_nothing_rather_than_noise():
    index = ChunkIndex.build(CORPUS)
    assert index.search("kubernetes ingress annotations") == []


def test_ranking_is_stable_for_the_same_query_and_corpus():
    """Two runs against one snapshot must produce the same excerpts, or the
    same requirement can yield two different designs."""
    first = ChunkIndex.build(CORPUS).search("claims status", top_k=5)
    second = ChunkIndex.build(CORPUS).search("claims status", top_k=5)

    assert [(c.id, s) for c, s in first] == [(c.id, s) for c, s in second]


def test_test_files_are_recognised_across_conventions():
    assert is_test_path("control-plane/api/tests/test_design.py")
    assert is_test_path("execution-plane/qa/test-scripts/claims-list.spec.ts")
    assert is_test_path("web/components/__tests__/Filter.test.tsx")
    assert is_test_path("api/tests/implementation_doubles.py")
    assert not is_test_path("demo-app/app/claims/page.tsx")
    assert not is_test_path("app/core/latest_protest.py")


def test_a_test_does_not_outrank_the_code_it_tests():
    """Measured failure this exists to prevent: on a naive ranking, four of
    the top six hits for a claims-filtering requirement were test files, so
    the design agent was grounded in tests rather than in the product."""
    corpus = dict(CORPUS)
    corpus["tests/test_filters.py"] = (
        "def test_filter_claims_by_status():\n"
        "    assert filter_claims([], 'open') == []\n"
        "def test_filter_claims_rejects_unknown_status():\n"
        "    pass\n"
    )
    top = ChunkIndex.build(corpus).search("filter claims by status", top_k=3)

    assert not top[0][0].is_test
    assert top[0][0].path == "app/claims/filters.py"


def test_an_empty_corpus_does_not_explode():
    assert ChunkIndex.build({}).search("anything") == []


# --- the adapter -----------------------------------------------------------


class _Graph:
    def __init__(self, paths: dict[str, set[str]], sha: str | None = "a" * 40) -> None:
        self._paths = paths
        self._sha = sha

    async def module_paths(self):
        return self._paths

    async def index_provenance(self):
        return {"commit_sha": self._sha, "pinned": bool(self._sha)}


class _Source:
    def __init__(self, sources: dict[str, str]) -> None:
        self.sources = sources
        self.reads = 0

    async def read_files(self, repo, ref, paths):
        self.reads += 1
        return {p: self.sources[p] for p in paths if p in self.sources}


@pytest.mark.asyncio
async def test_the_adapter_grounds_a_query_in_real_code():
    graph = _Graph({"claims": set(CORPUS)})
    context = IndexedRepoCodeDesignContext(graph, _Source(CORPUS), repo="acme/thing")

    snippets = await context.retrieve_context("filter claims by status", top_k=3)

    assert snippets
    assert snippets[0].doc_id.startswith("app/claims/filters.py")
    assert "def filter_claims" in snippets[0].text or "Claims filtering" in snippets[0].text


@pytest.mark.asyncio
async def test_the_index_is_reused_until_the_commit_changes():
    """Retrieval reads the snapshot the graph holds. Rebuilding on a changed
    commit rather than on a timer is what makes the same question against the
    same snapshot return the same excerpts."""
    graph = _Graph({"claims": set(CORPUS)})
    source = _Source(CORPUS)
    context = IndexedRepoCodeDesignContext(graph, source, repo="acme/thing")

    await context.retrieve_context("claims")
    await context.retrieve_context("invoice")
    assert source.reads == 1

    graph._sha = "b" * 40
    await context.retrieve_context("claims")
    assert source.reads == 2


@pytest.mark.asyncio
async def test_a_file_the_graph_knows_but_source_control_lost_is_survivable():
    graph = _Graph({"claims": set(CORPUS) | {"app/deleted.py"}})
    context = IndexedRepoCodeDesignContext(graph, _Source(CORPUS), repo="acme/thing")

    snippets = await context.retrieve_context("filter claims by status")
    assert snippets


@pytest.mark.asyncio
async def test_an_empty_graph_grounds_nothing_rather_than_guessing():
    context = IndexedRepoCodeDesignContext(_Graph({}), _Source({}), repo="acme/thing")
    assert await context.retrieve_context("anything") == []
