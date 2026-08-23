const STAGES: { key: string; label: string }[] = [
  { key: "requirements_intake", label: "Intake" },
  { key: "requirements_synthesis", label: "Synthesis" },
  { key: "ambiguity_check", label: "Ambiguity check" },
  { key: "gate_1", label: "Gate 1" },
  { key: "design_proposal", label: "Design" },
  { key: "gate_2", label: "Gate 2" },
  { key: "test_case_generation", label: "Test cases" },
  { key: "qa_execution", label: "QA run" },
  { key: "gate_3", label: "Gate 3" },
  { key: "build_deploy_stub", label: "Build / deploy" },
];

const STATUS_LABELS: Record<string, string> = {
  pending: "Queued...",
  synthesizing: "Analyzing requirement...",
  checking_ambiguity: "Checking for ambiguity...",
  awaiting_gate_1: "Awaiting requirements approval",
  designing: "Drafting design proposal...",
  awaiting_gate_2: "Awaiting design approval",
  generating_tests: "Generating test cases...",
  awaiting_qa_execution: "Running QA in CI...",
  awaiting_gate_3: "Awaiting test case approval",
  building: "Running build / deploy...",
  completed: "Completed",
  rejected_at_gate_1: "Rejected at requirements gate",
  rejected_at_gate_2: "Rejected at design gate",
  rejected_at_gate_3: "Rejected at test case gate",
  qa_failed: "QA run failed — did not reach the release gate",
  qa_timed_out: "QA run never reported — deadline passed",
  requirements_intake_failed: "Requirements intake failed — fell back to placeholder",
  synthesis_failed: "Synthesis failed — fell back to placeholder",
  ambiguity_check_failed: "Ambiguity check failed — fell back to placeholder",
  design_proposal_failed: "Design proposal failed — fell back to placeholder",
  test_case_generation_failed: "Test case generation failed — fell back to placeholder",
  build_deploy_failed: "Build / deploy failed — fell back to placeholder",
};

export function statusLabel(status: string): string {
  return STATUS_LABELS[status] ?? status;
}

export default function PipelineTimeline({
  status,
  completedNodes,
}: {
  status: string;
  completedNodes: Set<string>;
}) {
  return (
    <div className="card">
      <div style={{ fontSize: "1.05rem", fontWeight: 600, marginBottom: "0.75rem" }}>
        {statusLabel(status)}
      </div>
      <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
        {STAGES.map((s) => {
          const done = completedNodes.has(s.key);
          return (
            <div
              key={s.key}
              style={{
                padding: "0.3rem 0.6rem",
                borderRadius: "999px",
                border: "1px solid var(--border)",
                background: done ? "var(--success)" : "transparent",
                color: done ? "white" : "var(--muted)",
                fontSize: "0.78rem",
              }}
            >
              {s.label}
            </div>
          );
        })}
      </div>
    </div>
  );
}
