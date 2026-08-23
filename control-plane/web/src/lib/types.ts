export interface RunSummary {
  run_id: string;
  status: string;
  created_at: string;
  raw_requirement_text: string;
}

export interface PendingDispatch {
  phase: string;
  provider: string;
  state: string;
  external_url: string | null;
  started_at: string;
  deadline_at: string;
}

export interface RunDetail {
  run_id: string;
  status: string;
  state: Record<string, unknown>;
  pending_gate: Record<string, unknown> | null;
  // Separate from pending_gate on purpose: a run waiting on CI must not be
  // offered an Approve button, because no human decision is what unblocks it.
  pending_dispatch: PendingDispatch | null;
}

export interface AuditEntry {
  node_name: string;
  phase: "before" | "after";
  input_summary: Record<string, unknown>;
  output_summary: Record<string, unknown> | null;
  confidence_score: number | null;
  confirmed: boolean;
  human_decision: "approved" | "rejected" | null;
  timestamp: string;
}

export interface StreamedAuditEvent {
  node_name: string;
  phase: "before" | "after";
  output_summary: Record<string, unknown> | null;
  confirmed: boolean;
  human_decision: "approved" | "rejected" | null;
  timestamp: string;
}
