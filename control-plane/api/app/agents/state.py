import operator
from datetime import datetime
from typing import Annotated, Any, TypedDict

from pydantic import BaseModel

from app.core.confidence import ConfidenceEntry


class PipelineConfig(BaseModel):
    auto_approve_gates: bool = False
    max_node_retries: int = 2


class GateDecision(BaseModel):
    gate_name: str
    approved: bool
    feedback: str | None = None
    decided_at: datetime


class PipelineState(TypedDict, total=False):
    run_id: str
    # Which engagement's graph this run writes into. Carried on the state
    # rather than read from whatever is active when a phase happens to run:
    # a run is a decision about one codebase, and a phase that resolves the
    # project late would write a late-arriving assertion into whichever
    # project someone had switched to.
    #
    # It was absent, so the release phase had nothing to scope with and
    # hardcoded the default — writing its file nodes into a different
    # project's graph from the one the index had populated.
    project: str
    config: PipelineConfig
    raw_input: dict[str, Any]
    raw_requirements: dict[str, Any] | None
    requirements_synthesis: dict[str, Any] | None
    ambiguity_check: dict[str, Any] | None
    gate1_decision: GateDecision | None
    design_proposal: dict[str, Any] | None
    gate2_decision: GateDecision | None
    test_cases: list[dict[str, Any]]
    implementation: dict[str, Any] | None
    changed_paths: list[str]
    release: dict[str, Any] | None
    qa_result: dict[str, Any] | None
    graph_edges_written: int
    base_sha: str | None
    head_sha: str | None
    gate3_decision: GateDecision | None
    build_result: dict[str, Any] | None
    status: str
    confidence_entries: Annotated[list[ConfidenceEntry], operator.add]
