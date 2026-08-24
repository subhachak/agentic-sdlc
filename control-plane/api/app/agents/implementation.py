"""Phase 4 — Implementation: the agent writes the change, code decides whether
it may be proposed.

The prompt is deliberately narrow. The agent is given only the files the
design phase implicated, is told which components it may touch, and returns
whole files rather than a diff — diffs are where generated changes go wrong,
because a patch that does not apply is a failure with no useful message.

Nothing here executes what the agent wrote. It is written to a branch and
handed to the QA phase, which runs it where such things are safe to run.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

SYSTEM = """You are an implementation agent working on an existing codebase.

You are given a requirement, the design decision that addresses it, the
acceptance criteria the change must satisfy, and the current contents of the
files you may edit. Make the smallest change that satisfies the criteria.

Rules:
- Return the COMPLETE new contents of every file you change, not a diff.
- Only edit files you were given, or create new files inside the components
  you were told you may touch. A change outside them is rejected without
  being run.
- Match the surrounding code: its imports, its naming, its formatting, its
  error handling. Do not reformat code you are not otherwise changing.
- Do not add dependencies, edit CI workflows, or touch configuration.
- Explain the change in one or two sentences, in terms of the criteria it
  satisfies — not a list of the edits, which the diff already shows.

If the criteria cannot be satisfied by editing the files you were given, say
so in `blocked` and return no edits. That is a useful answer; a plausible
change to the wrong file is not."""


class ProposedEdit(BaseModel):
    path: str
    content: str
    reason: str = ""


class Implementation(BaseModel):
    summary: str
    edits: list[ProposedEdit] = Field(default_factory=list)
    blocked: str = ""


def build_prompt(
    *,
    requirement: str,
    design: dict[str, Any],
    criteria: list[dict[str, Any]],
    files: dict[str, str],
    allowed_components: list[str],
) -> str:
    criteria_text = "\n".join(f"  {c.get('id', '?')}: {c.get('text', '')}" for c in criteria)
    files_text = "\n\n".join(
        f"--- {path} ---\n{content}" for path, content in sorted(files.items())
    )
    return (
        f"Requirement:\n{requirement}\n\n"
        f"Design decision:\n{design.get('summary', '(none recorded)')}\n\n"
        f"Acceptance criteria this change must satisfy:\n{criteria_text or '  (none declared)'}\n\n"
        f"Components you may touch: {', '.join(allowed_components) or '(unrestricted)'}\n\n"
        f"Current file contents:\n{files_text or '(no files provided)'}"
    )
