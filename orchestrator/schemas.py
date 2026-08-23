"""Response shapes for every agent call.

These are passed to the Anthropic API as structured-output schemas, so the
model is constrained to return exactly this shape and the SDK validates it
before a node ever sees it. That replaces the old hand-rolled "strip the
markdown fence and hope json.loads works" path, where one stray token
aborted the run mid-PR.
"""
from __future__ import annotations

from pydantic import BaseModel


class DiffAnalysis(BaseModel):
    change_summary: str
    affected_areas: list[str]


class Scenario(BaseModel):
    id: str
    title: str
    type: str  # functional | regression | edge-case | negative
    target_route: str
    expected_outcome: str
    priority: str  # P1 | P2 | P3
    confidence: str  # high | medium | low
    ac_ref: str


class TestPlan(BaseModel):
    scenarios: list[Scenario]


class GeneratedSpec(BaseModel):
    code: str
