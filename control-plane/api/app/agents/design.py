"""Phase 3 — Architecture: decide what the change will touch.

Same shape as every other phase: the agent proposes, deterministic code
decides. What makes this one load-bearing is that the implementation phase is
constrained to what this phase names. If the design is a guess, containment
constrains nothing — it merely refuses whatever the guess missed.

The agent is given a catalogue of components that actually exist, drawn from
the context graph, and must name components and files from it. Anything it
invents is rejected before a human is asked to approve it.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

SYSTEM = """You are a software architect deciding how to implement a change in
an existing system.

You are given the requirement, its acceptance criteria, a catalogue of the
components that exist with their dependencies, and grounding excerpts from the
codebase. Decide the smallest set of components and files the change needs to
touch.

Rules:
- Name components and files ONLY from the catalogue. Anything not in it is
  rejected, and the run stops.
- Name specific files, not whole components. The implementation agent is shown
  the contents of exactly the files you name, so naming too few blocks it and
  naming too many buries the relevant code.
- Every acceptance criterion must be addressed by at least one component, or
  listed in `out_of_scope` with a reason.
- `rationale` explains why these components and not their neighbours. A human
  approves or rejects this change on the strength of that sentence.
- `risks` names what could break that the change does not touch directly —
  callers, contracts, stored data.

If the requirement cannot be implemented within the catalogue you were given,
say so in `blocked`. That is a useful answer. A design that names plausible
components it has not verified is not."""


class DesignProposal(BaseModel):
    summary: str
    rationale: str
    components: list[str] = Field(default_factory=list)
    files: list[str] = Field(default_factory=list)
    criteria_addressed: list[str] = Field(default_factory=list)
    out_of_scope: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    blocked: str = ""


def build_prompt(
    *,
    requirement: str,
    criteria: list[dict[str, Any]],
    catalogue: list[dict[str, Any]],
    snippets: list[dict[str, Any]],
    max_files: int,
) -> str:
    criteria_text = (
        "\n".join(f"  {c.get('id', '?')}: {c.get('text', '')}" for c in criteria)
        or "  (none declared)"
    )

    catalogue_text = "\n".join(
        f"  {c['id']}  ({c['files']} files)"
        + (f"\n     depends on: {', '.join(c['depends_on'])}" if c.get("depends_on") else "")
        + (f"\n     depended on by: {', '.join(c['dependents'])}" if c.get("dependents") else "")
        + (f"\n     files: {', '.join(c['paths'][:12])}" if c.get("paths") else "")
        for c in catalogue
    ) or "  (the context graph is empty — seed it from a repository first)"

    snippet_text = "\n\n".join(
        f"--- {s.get('title', s.get('doc_id', ''))} ---\n{s.get('text', '')[:1200]}"
        for s in snippets
    ) or "(no grounding excerpts available)"

    return (
        f"Requirement:\n{requirement}\n\n"
        f"Acceptance criteria:\n{criteria_text}\n\n"
        f"Component catalogue:\n{catalogue_text}\n\n"
        f"Name at most {max_files} files.\n\n"
        f"Grounding excerpts:\n{snippet_text}"
    )
