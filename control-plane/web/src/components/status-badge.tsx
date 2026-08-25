export type StatusTone = "ok" | "warn" | "crit" | "busy" | "idle" | "info";

export type RunStatusMeta = {
  label: string;
  tone: StatusTone;
  stage: "Intake" | "Requirements" | "Design" | "Implementation" | "QA" | "Release";
  terminal: boolean;
  waitingOn: "human" | "machine" | "agent" | "none";
};

const EXACT: Record<string, RunStatusMeta> = {
  pending: { label: "Queued", tone: "idle", stage: "Intake", terminal: false, waitingOn: "agent" },
  synthesizing: { label: "Analyzing requirement", tone: "busy", stage: "Requirements", terminal: false, waitingOn: "agent" },
  checking_ambiguity: { label: "Checking ambiguity", tone: "busy", stage: "Requirements", terminal: false, waitingOn: "agent" },
  awaiting_gate_1: { label: "Requirements approval", tone: "warn", stage: "Requirements", terminal: false, waitingOn: "human" },
  designing: { label: "Designing solution", tone: "busy", stage: "Design", terminal: false, waitingOn: "agent" },
  awaiting_gate_2: { label: "Design approval", tone: "warn", stage: "Design", terminal: false, waitingOn: "human" },
  generating_tests: { label: "Generating tests", tone: "busy", stage: "Implementation", terminal: false, waitingOn: "agent" },
  awaiting_qa_execution: { label: "QA in progress", tone: "busy", stage: "QA", terminal: false, waitingOn: "machine" },
  awaiting_gate_3: { label: "Release approval", tone: "warn", stage: "Release", terminal: false, waitingOn: "human" },
  building: { label: "Releasing", tone: "busy", stage: "Release", terminal: false, waitingOn: "machine" },
  completed: { label: "Completed", tone: "ok", stage: "Release", terminal: true, waitingOn: "none" },
  qa_failed: { label: "QA failed", tone: "crit", stage: "QA", terminal: true, waitingOn: "none" },
  qa_timed_out: { label: "QA timed out", tone: "crit", stage: "QA", terminal: true, waitingOn: "none" },
  design_rejected: { label: "Design rejected", tone: "crit", stage: "Design", terminal: true, waitingOn: "none" },
  design_blocked: { label: "Design blocked", tone: "crit", stage: "Design", terminal: true, waitingOn: "none" },
  implementation_rejected: { label: "Change rejected", tone: "crit", stage: "Implementation", terminal: true, waitingOn: "none" },
  implementation_blocked: { label: "Change blocked", tone: "crit", stage: "Implementation", terminal: true, waitingOn: "none" },
  implementation_failed: { label: "Implementation failed", tone: "crit", stage: "Implementation", terminal: true, waitingOn: "none" },
  release_failed: { label: "Release failed", tone: "crit", stage: "Release", terminal: true, waitingOn: "none" },
  rejected_at_gate_1: { label: "Requirements rejected", tone: "crit", stage: "Requirements", terminal: true, waitingOn: "none" },
  rejected_at_gate_2: { label: "Design rejected", tone: "crit", stage: "Design", terminal: true, waitingOn: "none" },
  rejected_at_gate_3: { label: "Release rejected", tone: "crit", stage: "Release", terminal: true, waitingOn: "none" },
};

export function runStatusMeta(status: string): RunStatusMeta {
  if (EXACT[status]) return EXACT[status];
  if (status.startsWith("awaiting_gate_")) {
    return { label: "Approval required", tone: "warn", stage: "Release", terminal: false, waitingOn: "human" };
  }
  if (status.endsWith("_failed")) {
    return { label: status.replaceAll("_", " "), tone: "crit", stage: "Release", terminal: true, waitingOn: "none" };
  }
  return {
    label: status.replaceAll("_", " "),
    tone: "busy",
    stage: "Implementation",
    terminal: false,
    waitingOn: "agent",
  };
}

export default function StatusBadge({ status }: { status: string }) {
  const meta = runStatusMeta(status);
  return <span className={`pill ${meta.tone}`}>{meta.label}</span>;
}
