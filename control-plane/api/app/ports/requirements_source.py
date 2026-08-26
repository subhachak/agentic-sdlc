"""Port: where the pipeline gets its requirement input from.

Widened by writing the second implementation. The port was
`fetch(text | file) -> {text, source_type, item_count}` with `source_type`
a closed `Literal["text", "csv"]` — which could not express "jira" without
editing this file, so the first real connector proved the seam was a seam in
name only.

Three things a system of record needs that freeform text does not:

  Identity.   A Jira issue is PROJ-123 at a URL, not a paragraph. Without
              carrying it, the REQUIREMENT node cannot point back at the
              record it came from and traceability stops at the platform
              boundary.
  Revision.   Requirements are edited. A decision made against the text as
              of one revision is not a decision about the text now, and an
              approval that cannot name what it approved is not evidence.
  Structure.  Acceptance criteria exist as fields, subtasks or links in the
              source. Flattening them into prose and asking a model to find
              them again discards information the client already curated.

Freeform text remains first-class — most demos and many real intakes are a
paragraph — so `RequirementsInput.text` and the flat `text` output are
unchanged, and an adapter that only does prose stays a two-line adapter.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from pydantic import BaseModel, Field


class RequirementRef(BaseModel):
    """How to ask for one item, in the terms of the system that owns it."""

    external_id: str
    # Optional query in the source's own language — JQL, WIQL, a saved
    # filter. Passed through rather than modelled: every tracker has one and
    # no two agree, and a lowest common denominator would be useless in all
    # of them.
    query: str = ""


class RequirementsInput(BaseModel):
    text: str | None = None
    file_bytes: bytes | None = None
    filename: str | None = None
    # Naming an item is an alternative to pasting it, not a replacement.
    ref: RequirementRef | None = None


class AcceptanceCriterion(BaseModel):
    """One testable statement, as the source expressed it.

    Carried with its own external id where the source has one, so a criterion
    tracked as a subtask keeps its identity into the graph and its coverage
    can be reported back against the same record.
    """

    external_id: str = ""
    text: str


class RequirementItem(BaseModel):
    """One requirement, with enough identity to be traced back."""

    external_id: str
    title: str = ""
    text: str = ""
    status: str = ""
    url: str = ""
    # Whatever the source uses to mean "this version": an updated timestamp,
    # a version number, an ETag. Opaque here and compared for equality only.
    revision: str = ""
    parent_id: str = ""
    labels: list[str] = Field(default_factory=list)
    criteria: list[AcceptanceCriterion] = Field(default_factory=list)


class SourceProvenance(BaseModel):
    """Which system answered, and when.

    An intake that cannot say where it came from produces a requirement the
    audit trail cannot attribute — the same failure as an index that cannot
    name its commit.
    """

    system: str = ""
    instance: str = ""
    fetched_at: str = ""
    adapter_version: str = ""


class RequirementsDoc(BaseModel):
    # The flat view. Unchanged, and still what the synthesis agent reads.
    text: str
    # Open, not an enum. The closed Literal was what made a new source a
    # change to the port rather than a new adapter.
    source_type: str
    item_count: int
    # The structured view. Empty for a freeform adapter, which is honest:
    # prose has no identity to carry.
    items: list[RequirementItem] = Field(default_factory=list)
    provenance: SourceProvenance = Field(default_factory=SourceProvenance)


class RequirementsSource(Protocol):
    async def fetch(self, raw: RequirementsInput) -> RequirementsDoc: ...


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")
