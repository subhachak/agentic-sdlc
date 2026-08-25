"""Shared fixtures.

The point of these tests is the deterministic half of the pipeline: the
testability gate, the script matcher, and the results parser. Those are the
functions that decide whether a PR is judged pass or fail, so they are the
ones that must not be able to drift silently.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Read the fixture, not the live export. execution-plane/qa/code-graph.json is
# written by the control plane on every sync, so it cannot also be the thing
# these tests assert against — pointing the platform at a different repository
# rewrote it and nine tests failed for reasons nothing in them mentioned.
# Set before orchestrator.paths is imported, since it resolves at module load.
os.environ.setdefault(
    "QA_CODE_GRAPH", str(Path(__file__).resolve().parent / "fixtures" / "code-graph.json")
)


def _test(status: str) -> dict:
    return {
        "projectName": "chromium",
        "expectedStatus": "passed",
        "status": status,
        "results": [{"status": "passed" if status == "expected" else "failed", "duration": 12}],
    }


def _spec(title: str, status: str = "expected") -> dict:
    return {"title": title, "ok": status == "expected", "tests": [_test(status)]}


@pytest.fixture
def playwright_report():
    """A real Playwright JSON reporter payload shape: the tests live under
    suites[].specs[].tests[], and the readable title is on the spec."""

    def _build(*specs: dict, nested: list[dict] | None = None) -> dict:
        return {
            "config": {"rootDir": "/repo/generated-tests"},
            "suites": [
                {
                    "title": "claims-list.spec.ts",
                    "file": "claims-list.spec.ts",
                    "column": 0,
                    "line": 0,
                    "specs": list(specs),
                    "suites": nested or [],
                }
            ],
            "errors": [],
        }

    return _build


@pytest.fixture
def spec():
    return _spec


@pytest.fixture
def manifest():
    return [
        {
            "id": "claims-list-renders",
            "file": "claims-list.spec.ts",
            "route": "/claims",
            "tags": ["claims", "list", "regression"],
            "covers": "Claims table renders all claims with id, policyholder, status, last updated",
        }
    ]
