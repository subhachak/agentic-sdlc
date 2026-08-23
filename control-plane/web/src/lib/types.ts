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

export interface DashboardData {
  runs: {
    total: number;
    by_status: Record<string, number>;
    awaiting_human: number;
    awaiting_machine: number;
    working: number;
    finished: number;
  };
  recent: {
    run_id: string;
    status: string;
    created_at: string;
    requirement: string;
    waiting_on: "awaiting_human" | "awaiting_machine" | "working" | "finished";
  }[];
  coverage: {
    criteria: number;
    untested: number;
    tested: number;
    gaps: { id: string; text: string }[];
  };
  graph: {
    nodes: Record<string, number>;
    edges: Record<string, number>;
    components: number;
    dependencies: number;
  };
  dispatches: Record<string, number>;
  active: {
    model_provider: string;
    execution_target: string;
    index_source: string;
    indexed_repo: string | null;
    gates: string;
  };
}

export interface SettingEntry {
  key: string;
  label: string;
  group: string;
  kind: "mutable" | "secret" | "static";
  type: "enum" | "text" | "int" | "float" | "bool";
  options: string[];
  help: string;
  placeholder: string;
  overridden: boolean;
  value: string | number | boolean | null;
  configured?: boolean;
}

export interface SettingChange {
  key: string;
  label: string;
  previous: string | number | boolean | null;
  value: string | number | boolean | null;
  changed_by: string;
  at: string;
}

export interface ConfigData {
  settings: SettingEntry[];
  history: SettingChange[];
  active: Record<string, string>;
}

export interface ComponentEntry {
  id: string;
  files: number;
  depends_on: { target: string; weight: number }[];
}
