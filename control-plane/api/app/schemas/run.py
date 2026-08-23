from pydantic import BaseModel


class CreateRunResponse(BaseModel):
    run_id: str
    status: str


class ApproveRequest(BaseModel):
    gate: str
    approved: bool
    feedback: str | None = None


class ApproveResponse(BaseModel):
    run_id: str
    status: str


class RunSummary(BaseModel):
    run_id: str
    status: str
    created_at: str
    raw_requirement_text: str


class RunDetail(BaseModel):
    run_id: str
    status: str
    state: dict
    pending_gate: dict | None = None


class AuditEntryOut(BaseModel):
    node_name: str
    phase: str
    input_summary: dict
    output_summary: dict | None
    confidence_score: float | None
    confirmed: bool
    human_decision: str | None
    timestamp: str
