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


class PendingDispatch(BaseModel):
    phase: str
    provider: str
    state: str
    external_url: str | None = None
    started_at: str
    deadline_at: str


class RunDetail(BaseModel):
    run_id: str
    status: str
    state: dict
    pending_gate: dict | None = None
    # Distinct from pending_gate on purpose: without it the console cannot
    # tell "waiting for a person" from "waiting for a machine", and would
    # offer an Approve button for a CI job nobody should be approving.
    pending_dispatch: PendingDispatch | None = None


class AuditEntryOut(BaseModel):
    node_name: str
    phase: str
    input_summary: dict
    output_summary: dict | None
    confidence_score: float | None
    confirmed: bool
    human_decision: str | None
    timestamp: str
