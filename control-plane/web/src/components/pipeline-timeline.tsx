import { runStatusMeta } from "@/components/status-badge";

const STAGES = [
  { key: "requirements_intake", label: "Intake" },
  { key: "requirements_synthesis", label: "Synthesize" },
  { key: "ambiguity_check", label: "Clarify" },
  { key: "gate_1", label: "Req. gate" },
  { key: "design_proposal", label: "Design" },
  { key: "gate_2", label: "Design gate" },
  { key: "test_case_generation", label: "Tests" },
  { key: "implementation", label: "Implement" },
  { key: "qa_execution", label: "QA" },
  { key: "gate_3", label: "Release gate" },
  { key: "release", label: "Release" },
] as const;

const MOBILE_STAGES = [
  { key: "requirements_intake", label: "Intake", phase: "Intake" },
  { key: "gate_1", label: "Requirements", phase: "Requirements" },
  { key: "gate_2", label: "Design", phase: "Design" },
  { key: "implementation", label: "Implement", phase: "Implementation" },
  { key: "qa_execution", label: "QA", phase: "QA" },
  { key: "release", label: "Release", phase: "Release" },
] as const;

const ACTIVE_NODE: Record<string, string | null> = {
  pending: "requirements_intake",
  synthesizing: "requirements_synthesis",
  checking_ambiguity: "ambiguity_check",
  awaiting_gate_1: "gate_1",
  designing: "design_proposal",
  awaiting_gate_2: "gate_2",
  generating_tests: "test_case_generation",
  awaiting_qa_execution: "qa_execution",
  awaiting_gate_3: "gate_3",
  building: "release",
  completed: null,
  qa_failed: "qa_execution",
  qa_timed_out: "qa_execution",
  design_rejected: "design_proposal",
  design_blocked: "design_proposal",
  implementation_rejected: "implementation",
  implementation_blocked: "implementation",
  implementation_failed: "implementation",
  release_failed: "release",
  rejected_at_gate_1: "gate_1",
  rejected_at_gate_2: "gate_2",
  rejected_at_gate_3: "gate_3",
};

export default function PipelineTimeline({ status, completedNodes }: { status: string; completedNodes: Set<string> }) {
  const meta = runStatusMeta(status);
  const activeNode = ACTIVE_NODE[status] ?? null;
  const completed = STAGES.filter((stage) => completedNodes.has(stage.key)).length;

  return (
    <section className="panel pipeline-panel" aria-label="Delivery lifecycle">
      <div className="pipeline-summary" aria-live="polite">
        <span><strong>{meta.label}</strong><span> · {meta.stage} phase</span></span>
        <span>{completed} of {STAGES.length} controls completed</span>
      </div>
      <ol className="pipeline pipeline-desktop">
        {STAGES.map((stage) => {
          const done = completedNodes.has(stage.key);
          const active = stage.key === activeNode && !done;
          const failed = active && meta.tone === "crit";
          return (
            <li
              key={stage.key}
              className={`pipeline-stage ${done ? "done" : ""} ${active ? "active" : ""} ${failed ? "failed" : ""}`}
              aria-current={active ? "step" : undefined}
            >
              <span>{stage.label}</span>
              <span className="sr-only">{done ? "completed" : active ? failed ? "failed here" : "current step" : "not started"}</span>
            </li>
          );
        })}
      </ol>
      <ol className="pipeline pipeline-mobile">
        {MOBILE_STAGES.map((stage) => {
          const done = completedNodes.has(stage.key);
          const active = meta.stage === stage.phase && !done;
          const failed = active && meta.tone === "crit";
          return (
            <li key={stage.key} className={`pipeline-stage ${done ? "done" : ""} ${active ? "active" : ""} ${failed ? "failed" : ""}`} aria-current={active ? "step" : undefined}>
              <span>{stage.label}</span>
              <span className="sr-only">{done ? "completed" : active ? failed ? "failed here" : "current step" : "not started"}</span>
            </li>
          );
        })}
      </ol>
    </section>
  );
}
