"""Retrieval over source code: chunking, and ranking chunks against a query.

The third graph. Traceability is audited and accumulated, code intelligence
is derived and rebuilt, and this one is derived, rebuilt, and *disposable* —
nothing is gated on a retrieval score. That is the point of keeping it
separate: a bad ranking makes an agent's proposal worse, and the
deterministic gates then reject it. A bad dependency edge would let something
through.

Lexical rather than embedding-based, deliberately. Code retrieval is largely
symbol lookup, where exact identifier matching is strong and an embedding is
guessing; BM25 needs no model, no key, no network, and no nightly re-embed,
so it is the honest default. The port stays open for an embedding adapter
where a client wants prose recall over their design documents too.

Nothing here does I/O. Chunking Python uses `ast`, so those boundaries are
exact rather than a regex approximation.
"""

from __future__ import annotations

import ast
import math
import re
from collections import Counter
from dataclasses import dataclass, field

from app.core.source_kinds import is_test_path

# Chunk text is capped so one enormous generated file cannot dominate a
# prompt. Truncation is marked, because an agent that cannot see a file ends
# should know that rather than infer it.
MAX_CHUNK_CHARS = 2400
TRUNCATION_MARK = "\n… (truncated)"

# Identifier boundaries: snake_case, camelCase, dots, slashes, dashes.
_SPLIT = re.compile(r"[^A-Za-z0-9]+")
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")

# Words that appear in nearly every file and carry no retrieval signal. Kept
# short on purpose: BM25 already discounts common terms, and an aggressive
# list removes real query words like "type" or "import".
_STOPWORDS = frozenset("""
a an the and or not is are was were be been being to of in on at by for with
from as if else elif then this that these those it its self def class return
import export const let var function async await new null none true false
""".split())

# Weighted fields. A query naming a symbol should find that symbol, not every
# file that mentions it in passing, so name and path tokens are counted
# several times over rather than scored in a second pass.
NAME_WEIGHT = 4
PATH_WEIGHT = 2

# Tests match the vocabulary of the thing they test, so on a naive ranking
# they crowd out the thing itself — measured on this repository, four of the
# top six hits for "add a filter to the claims page" were test files. They are
# demoted rather than excluded: "how is this covered" is a real question, and
# a test is often the clearest statement of intended behaviour. It just must
# not be what an agent designs against.
TEST_PENALTY = 0.35


_JS_SYMBOL = re.compile(
    r"""(?m)^[ \t]*(?:export\s+)?(?:default\s+)?(?:async\s+)?"""
    r"""(function|class|const|let|var|interface|type|enum)\s+([A-Za-z_$][\w$]*)"""
)


def tokenize(text: str) -> list[str]:
    """Split text the way identifiers are actually written.

    `getClaimStatus` and `get_claim_status` must both produce the tokens a
    requirement written in English would use.
    """
    tokens: list[str] = []
    for piece in _SPLIT.split(text):
        if not piece:
            continue
        for part in _CAMEL.split(piece):
            lowered = part.lower()
            if len(lowered) > 1 and lowered not in _STOPWORDS:
                tokens.append(lowered)
    return tokens


@dataclass
class Chunk:
    """A retrievable piece of the codebase.

    Either a whole file's header — its module docstring and what it imports,
    which is what tells a reader what the file is *for* — or one top-level
    definition.
    """

    path: str
    kind: str          # "file" | "symbol"
    name: str
    text: str
    start_line: int = 1
    end_line: int = 1
    language: str = "unknown"

    @property
    def is_test(self) -> bool:
        return is_test_path(self.path)

    @property
    def id(self) -> str:
        return self.path if self.kind == "file" else f"{self.path}#{self.name}"

    @property
    def title(self) -> str:
        if self.kind == "file":
            return self.path
        return f"{self.path}:{self.start_line} — {self.name}"

    def tokens(self) -> list[str]:
        return (
            tokenize(self.name) * NAME_WEIGHT
            + tokenize(self.path) * PATH_WEIGHT
            + tokenize(self.text)
        )


def _clip(text: str) -> str:
    if len(text) <= MAX_CHUNK_CHARS:
        return text
    return text[:MAX_CHUNK_CHARS] + TRUNCATION_MARK


def _file_header(path: str, text: str, language: str, upto: int) -> Chunk | None:
    """The top of a file: docstring, imports, module constants.

    Retrieved on its own because "which file handles claims filtering" is
    answered by a file's preamble far more often than by any one function
    inside it.
    """
    lines = text.splitlines()[:upto]
    body = "\n".join(lines).strip()
    if not body:
        return None
    return Chunk(
        path=path,
        kind="file",
        name=path.rsplit("/", 1)[-1],
        text=_clip(body),
        start_line=1,
        end_line=min(upto, len(lines)) or 1,
        language=language,
    )


def chunk_python(path: str, text: str) -> list[Chunk]:
    """One chunk per top-level definition, with exact boundaries from `ast`.

    A syntax error yields the file header alone rather than nothing: a file
    that does not parse is still a file the agent may need to see.
    """
    try:
        tree = ast.parse(text)
    except SyntaxError:
        header = _file_header(path, text, "python", 40)
        return [header] if header else []

    lines = text.splitlines()
    chunks: list[Chunk] = []
    first_def = len(lines)

    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        start = min(
            [node.lineno] + [d.lineno for d in getattr(node, "decorator_list", [])]
        )
        end = getattr(node, "end_lineno", start) or start
        first_def = min(first_def, start)
        chunks.append(
            Chunk(
                path=path,
                kind="symbol",
                name=node.name,
                text=_clip("\n".join(lines[start - 1 : end])),
                start_line=start,
                end_line=end,
                language="python",
            )
        )

    header = _file_header(path, text, "python", max(first_def - 1, 1))
    return ([header] if header else []) + chunks


def chunk_javascript(path: str, text: str, language: str) -> list[Chunk]:
    """Regex-bounded, unlike the Python case.

    A chunk runs from one top-level declaration to the next, which over-reads
    where declarations nest and under-reads nothing. Good enough to retrieve
    with; it is never the basis of a gate.
    """
    lines = text.splitlines()
    matches = [
        (text[: m.start()].count("\n") + 1, m.group(2))
        for m in _JS_SYMBOL.finditer(text)
    ]

    chunks: list[Chunk] = []
    for index, (start, name) in enumerate(matches):
        end = matches[index + 1][0] - 1 if index + 1 < len(matches) else len(lines)
        chunks.append(
            Chunk(
                path=path,
                kind="symbol",
                name=name,
                text=_clip("\n".join(lines[start - 1 : end])),
                start_line=start,
                end_line=max(end, start),
                language=language,
            )
        )

    upto = matches[0][0] - 1 if matches else min(len(lines), 40)
    header = _file_header(path, text, language, max(upto, 1))
    return ([header] if header else []) + chunks


def chunk_file(path: str, text: str) -> list[Chunk]:
    if path.endswith(".py"):
        return chunk_python(path, text)
    if path.endswith((".ts", ".tsx")):
        return chunk_javascript(path, text, "typescript")
    if path.endswith((".js", ".jsx", ".mjs", ".cjs")):
        return chunk_javascript(path, text, "javascript")
    header = _file_header(path, text, "unknown", 40)
    return [header] if header else []


@dataclass
class ChunkIndex:
    """BM25 over code chunks.

    Okapi BM25 with the usual constants. Rebuilt from source rather than
    persisted: at the scale one repository indexes to, building is faster
    than deciding whether a cache is stale.
    """

    k1: float = 1.5
    b: float = 0.75
    chunks: list[Chunk] = field(default_factory=list)
    _postings: dict[str, dict[int, int]] = field(default_factory=dict)
    _lengths: list[int] = field(default_factory=list)
    _avg_length: float = 0.0

    @classmethod
    def build(cls, sources: dict[str, str]) -> "ChunkIndex":
        index = cls()
        for path in sorted(sources):
            for chunk in chunk_file(path, sources[path]):
                index._add(chunk)
        index._finalise()
        return index

    def _add(self, chunk: Chunk) -> None:
        position = len(self.chunks)
        self.chunks.append(chunk)
        counts = Counter(chunk.tokens())
        for term, count in counts.items():
            self._postings.setdefault(term, {})[position] = count
        self._lengths.append(sum(counts.values()))

    def _finalise(self) -> None:
        self._avg_length = (
            sum(self._lengths) / len(self._lengths) if self._lengths else 0.0
        )

    def __len__(self) -> int:
        return len(self.chunks)

    def search(self, query: str, top_k: int = 8) -> list[tuple[Chunk, float]]:
        """Rank chunks against a query, best first.

        Scores are relative to this query and this corpus — comparable within
        one result set, meaningless across two. Nothing downstream may treat
        them as a confidence.
        """
        terms = tokenize(query)
        if not terms or not self.chunks:
            return []

        total = len(self.chunks)
        scores: dict[int, float] = {}
        for term in set(terms):
            postings = self._postings.get(term)
            if not postings:
                continue
            # BM25's idf, with the +1 that keeps a term present in every
            # document at zero rather than negative.
            idf = math.log(1 + (total - len(postings) + 0.5) / (len(postings) + 0.5))
            for position, frequency in postings.items():
                length_norm = 1 - self.b + self.b * (
                    self._lengths[position] / self._avg_length
                    if self._avg_length
                    else 1.0
                )
                numerator = frequency * (self.k1 + 1)
                denominator = frequency + self.k1 * length_norm
                scores[position] = scores.get(position, 0.0) + idf * (
                    numerator / denominator
                )

        for position in scores:
            if self.chunks[position].is_test:
                scores[position] *= TEST_PENALTY

        ranked = sorted(scores.items(), key=lambda kv: (-kv[1], self.chunks[kv[0]].id))
        return [(self.chunks[position], round(score, 4)) for position, score in ranked[:top_k]]
