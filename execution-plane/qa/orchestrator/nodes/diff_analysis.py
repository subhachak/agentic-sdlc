"""Phase 1 — Discovery for this PR: what changed, and what does it touch.

Agent proposes a summary. No gate here (nothing to be "ready" yet) — this
phase just turns a raw diff into structured context for the test-plan node.
"""
from __future__ import annotations

import re

from orchestrator.llm import ask
from orchestrator.schemas import DiffAnalysis
from orchestrator.state import PipelineState

SYSTEM = """You are a QA discovery agent. Given a git diff and known feature
context, summarize what changed in plain language and list the affected
user-facing areas (routes, modules, API endpoints). Be concrete — name
routes and elements, don't generalize. affected_areas entries look like
"/claims (status filter added)"."""


def changed_paths(diff: str) -> list[str]:
    """File paths touched by the diff, read straight from its headers.

    Deterministic on purpose: which files changed is a fact, and asking a
    model for it would make blast-radius scope depend on a summary.
    """
    return sorted({m.group(1) for m in re.finditer(r"^diff --git a/(\S+)", diff, re.M)})


def run(state: PipelineState) -> PipelineState:
    diff = state["diff_text"]
    features = state.get("features_context", {})

    user = (
        f"Known features (for context, may be incomplete for new work):\n"
        f"{features}\n\n"
        f"Git diff for this PR:\n```diff\n{diff}\n```"
    )
    result = ask(SYSTEM, user, DiffAnalysis)

    return {
        **state,
        "change_summary": result.change_summary,
        "affected_areas": result.affected_areas,
        "changed_paths": changed_paths(diff),
    }
