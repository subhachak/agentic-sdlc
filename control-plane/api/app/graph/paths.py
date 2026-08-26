"""One canonical form for a repository path.

Node identity is derived from the external id, and for a source artifact
that id is a path. Nothing normalised it, so `app/a.ts`, `./app/a.ts`,
`/app/a.ts`, `app//a.ts` and `app/./a.ts` were five different nodes for one
file — and the sixth, `APP/a.ts`, a case variant the indexer can genuinely
emit on a case-insensitive filesystem.

That is not theoretical. The indexer produces clean relative paths, but
agent-authored paths reach identity directly: the release phase writes a
CONTAINS edge for every file the implementation agent reports, and a client's
coding agent decides that spelling. One `./` prefix creates a phantom node
that no import edge points at, so the file looks unreferenced and its blast
radius is empty.

The execution plane already had `_normalise` for the comparison side of the
same problem. This is the same rule, applied where identity is minted, and
the two are pinned together by a test.
"""

from __future__ import annotations

import posixpath


def canonical(path: str) -> str:
    """The one spelling of a repository-relative path.

    Case is deliberately preserved. Two files differing only in case are
    distinct on the filesystems this indexes, and folding case would merge
    them into one node — trading a duplicate for a collision, which is the
    worse failure.
    """
    if not path:
        return ""
    text = path.strip().replace("\\", "/")
    # Collapses `.` segments, doubled separators and resolves `..` textually.
    # normpath on an empty result yields ".", which is not a path.
    text = posixpath.normpath(text)
    text = text.lstrip("/")
    while text.startswith("../"):
        # A path escaping the repository root is not repository-relative.
        # Kept rather than rejected: refusing here would fail a run over a
        # spelling, and the containment check is what should reject it.
        text = text[3:]
    return "" if text in (".", "..") else text
