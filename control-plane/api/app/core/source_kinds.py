"""Classifying a source path by what kind of code it is.

Used in three places that must agree: retrieval ranking, dependency-edge
classification, and regression scoping. A test file importing a module is a
real edge — it is how you find which tests to run — but it is not evidence
that the module is widely depended on. Measured on this repository, 30% of
import edges originate in test files, and the highest fan-in file in a
sibling repository had 67 importers of which 48% were tests. Ranking hubs by
raw fan-in therefore ranks them by how well tested they are.

Kept here rather than beside any one consumer so the three cannot drift.
"""

from __future__ import annotations

_TEST_DIRECTORIES = (
    "/tests/", "/test/", "/__tests__/", "/spec/", "/specs/",
    "/test-scripts/", "/generated-tests/", "/e2e/", "/evals/", "/fixtures/",
)

_TEST_FILENAMES = frozenset({"conftest.py", "setup.py"})

_TEST_SUFFIXES = (
    "_test.py", "_test.go",
    ".spec.ts", ".spec.tsx", ".spec.js", ".spec.jsx",
    ".test.ts", ".test.tsx", ".test.js", ".test.jsx",
)


def is_test_path(path: str) -> bool:
    """Whether a path holds test, fixture or double code rather than product code.

    Convention-based, and therefore wrong on a codebase that does not follow
    one. It is only ever used to weight — never to exclude, and never to
    decide whether something is admissible — so a miss costs ranking quality
    rather than correctness.
    """
    lowered = path.lower()
    name = lowered.rsplit("/", 1)[-1]
    return (
        any(directory in f"/{lowered}" for directory in _TEST_DIRECTORIES)
        or name.startswith("test_")
        or name.endswith(_TEST_SUFFIXES)
        or name in _TEST_FILENAMES
        or "doubles" in name
        or "mock" in name
    )
