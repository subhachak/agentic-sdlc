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
    config: PipelineConfig
    raw_input: dict[str, Any]
    raw_requirements: dict[str, Any] | None
    requirements_synthesis: dict[str, Any] | None
    ambiguity_check: dict[str, Any] | None
    gate1_decision: GateDecision | None
    design_proposal: dict[str, Any] | None
    gate2_decision: GateDecision | None
    test_cases: list[dict[str, Any]]
    gate3_decision: GateDecision | None
    build_result: dict[str, Any] | None
    status: str
    confidence_entries: Annotated[list[ConfidenceEntry], operator.add]
