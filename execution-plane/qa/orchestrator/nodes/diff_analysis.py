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


# `git diff --name-status -z` emits NUL-separated records: a status, then a
# path — except renames and copies, which emit the status, the old path, and
# the new path. Parsing that is what makes rename handling correct; the diff
# headers cannot express it, because `diff --git a/old b/new` puts the path
# that no longer exists first.
_RENAME_OR_COPY = ("R", "C")


def changed_paths_from_name_status(raw: str) -> list[str]:
    """Paths a change touches, from git's machine-readable status output.

    Reads both ends of a rename and a copy. The earlier version took only the
    new path for a rename, reasoning that the old one no longer exists so
    nothing can be tested against it — which confused running a test with
    scoping one. Nothing runs against a path that is gone, but everything
    that imported it is recorded in the graph under that path, because the
    graph describes the base commit. Drop it and a rename reaches nobody.

    NUL separation means a path containing a space or a quote survives
    intact, which the whitespace-split header parse did not.
    """
    fields = [f for f in raw.split("\0") if f]
    paths: set[str] = set()
    index = 0
    while index < len(fields):
        status = fields[index]
        if status.startswith(_RENAME_OR_COPY) and index + 2 < len(fields):
            # Both ends. Taking only the new path for a rename was wrong for
            # the same reason it is wrong in the control plane's adapter: the
            # code graph records a file's importers against the path it had
            # at the base commit, so the renamed-away path is the only key
            # that finds them. Dropping it turns a rename into a change that
            # reached nothing.
            paths.add(fields[index + 1])
            paths.add(fields[index + 2])
            index += 3
            continue
        if index + 1 < len(fields):
            # D (deleted) included deliberately: removing a file is a change
            # its dependents have to survive.
            paths.add(fields[index + 1])
        index += 2
    return sorted(paths)


def changed_paths(diff: str) -> list[str]:
    r"""Fallback: file paths read out of diff headers.

    Weaker than the name-status parse and kept only for the case where a diff
    is all that is available. `diff --git a/old b/new` names the pre-rename
    path first, so a renamed file is scoped to a path that no longer exists,
    and `\S+` truncates any path containing a space.
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
        # Preferred source is git's own status output, computed before the
        # graph ran. The header parse is a fallback for a diff with no
        # accompanying status.
        "changed_paths": state.get("changed_paths") or changed_paths(diff),
    }
