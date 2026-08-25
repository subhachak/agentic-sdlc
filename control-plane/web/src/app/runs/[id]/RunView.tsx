"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import { approveGate, eventsUrl, getAuditTrail, getRun, nudgeDispatch } from "@/lib/api";
import type { AuditEntry, RunDetail } from "@/lib/types";
import PipelineTimeline from "@/components/pipeline-timeline";
import DispatchWaitingPanel from "@/components/dispatch-waiting-panel";
import GateApprovalPanel from "@/components/gate-approval-panel";
import AuditLogView from "@/components/audit-log-view";
import StatusBadge, { runStatusMeta } from "@/components/status-badge";

const STATUS_TO_GATE: Record<string, string> = {
  awaiting_gate_1: "gate_1",
  awaiting_gate_2: "gate_2",
  awaiting_gate_3: "gate_3",
};

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function list(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function string(value: unknown, fallback = "Not reported") {
  return typeof value === "string" && value.trim() ? value : fallback;
}

function dedupeAudit(entries: AuditEntry[]) {
  const seen = new Set<string>();
  return entries.filter((entry) => {
    const key = `${entry.node_name}|${entry.phase}|${entry.timestamp}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function EvidenceSummary({ state }: { state: Record<string, unknown> }) {
  const synthesis = record(state.requirements_synthesis);
  const ambiguity = record(state.ambiguity_check);
  const design = record(state.design_proposal);
  const impact = record(design.impact);
  const implementation = record(state.implementation);
  const qa = record(state.qa_result);
  const qaPayload = record(qa.payload);
  const tests = list(state.test_cases);
  const modules = list(design.modules);
  const designFiles = list(design.files);
  const impactedFiles = list(impact.affected_files);
  const implementationFiles = list(implementation.files);
  const regression = record(qaPayload.regression_scope);
  const scenarios = list(qaPayload.test_plan || qaPayload.scenarios);

  return (
    <section className="panel">
      <div className="panel-head"><div><h2>Run evidence</h2><p>Human-readable checkpoints produced by the workflow. Technical payloads remain in the audit section.</p></div></div>
      <div className="evidence-summary-grid">
        <article className="evidence-summary-card">
          <span className="evidence-card-index">01</span>
          <span className="context-label">Requirement baseline</span>
          <h3>{string(synthesis.summary, "Requirement synthesis pending")}</h3>
          <div className="evidence-card-meta"><span className={`pill ${ambiguity.passed === false ? "warn" : ambiguity.passed === true ? "ok" : "idle"}`}>{ambiguity.passed === false ? "Ambiguity found" : ambiguity.passed === true ? "Clarity check passed" : "Awaiting analysis"}</span></div>
        </article>

        <article className="evidence-summary-card">
          <span className="evidence-card-index">02</span>
          <span className="context-label">Design and structural impact</span>
          <h3>{string(design.summary, "Design evidence pending")}</h3>
          <div className="evidence-card-stats"><span><strong>{modules.length}</strong> modules</span><span><strong>{designFiles.length || impactedFiles.length}</strong> files in scope</span></div>
        </article>

        <article className="evidence-summary-card">
          <span className="evidence-card-index">03</span>
          <span className="context-label">Implementation</span>
          <h3>{string(implementation.summary, implementationFiles.length ? `${implementationFiles.length} files changed` : "Implementation evidence pending")}</h3>
          <div className="evidence-card-stats"><span><strong>{implementationFiles.length}</strong> changed files</span><span>{string(implementation.agent, "Agent not reported")}</span></div>
        </article>

        <article className="evidence-summary-card">
          <span className="evidence-card-index">04</span>
          <span className="context-label">Test and QA assurance</span>
          <h3>{string(qa.feedback || qa.state, tests.length ? `${tests.length} generated test case${tests.length === 1 ? "" : "s"}` : "QA evidence pending")}</h3>
          <div className="evidence-card-stats"><span><strong>{tests.length || scenarios.length}</strong> scenarios</span><span><strong>{Object.keys(regression).length}</strong> regression facts</span></div>
        </article>
      </div>

      {(modules.length > 0 || designFiles.length > 0 || impactedFiles.length > 0) && (
        <details className="disclosure">
          <summary>Design scope and structural reach</summary>
          <div className="panel-body">
            <div className="scope-evidence-grid">
              <div><span className="context-label">Proposed modules</span><div className="dependency-list">{modules.map((module, index) => <span className="dependency-chip" key={index}>{string(module)}</span>)}</div></div>
              <div><span className="context-label">Files in proposed scope</span><div className="dependency-list">{[...designFiles, ...impactedFiles].slice(0, 12).map((file, index) => <span className="dependency-chip" key={index}>{string(file)}</span>)}</div></div>
            </div>
          </div>
        </details>
      )}
    </section>
  );
}

export default function RunView({ runId }: { runId: string }) {
  const [run, setRun] = useState<RunDetail | null>(null);
  const [entries, setEntries] = useState<AuditEntry[]>([]);
  const [loadingError, setLoadingError] = useState<string | null>(null);
  const [decisionPending, setDecisionPending] = useState(false);
  const [decisionError, setDecisionError] = useState<string | null>(null);
  const sourceRef = useRef<EventSource | null>(null);

  async function refreshAll() {
    try {
      const [detail, audit] = await Promise.all([getRun(runId), getAuditTrail(runId)]);
      setRun(detail);
      setEntries(dedupeAudit(audit));
      setLoadingError(null);
    } catch (reason) {
      setLoadingError(reason instanceof Error ? reason.message : String(reason));
    }
  }

  useEffect(() => {
    void refreshAll();
    const source = new EventSource(eventsUrl(runId));
    sourceRef.current = source;
    source.addEventListener("audit", () => { void refreshAll(); });
    source.addEventListener("done", () => { void refreshAll(); source.close(); });
    source.onerror = () => { /* EventSource reconnects; the visible state remains the last confirmed API result. */ };
    return () => { source.close(); sourceRef.current = null; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId]);

  async function onDecide(gateName: string, approved: boolean, feedback?: string) {
    setDecisionPending(true);
    setDecisionError(null);
    try {
      await approveGate(runId, gateName, approved, feedback);
      await refreshAll();
    } catch (reason) {
      setDecisionError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setDecisionPending(false);
    }
  }

  const completedNodes = useMemo(() => new Set(entries.filter((entry) => entry.phase === "after").map((entry) => entry.node_name)), [entries]);

  if (!run) {
    return (
      <main>
        <Link href="/runs" className="back-link">← Delivery runs</Link>
        {loadingError ? <div className="notice crit" role="alert"><h3>The run could not be loaded</h3><p>{loadingError}</p><button type="button" className="secondary" style={{ marginTop: 10 }} onClick={() => void refreshAll()}>Try again</button></div> : <section className="panel"><div className="panel-body"><p className="muted">Loading governed run evidence…</p></div></section>}
      </main>
    );
  }

  const state = record(run.state);
  const rawInput = record(state.raw_input);
  const rawRequirements = record(state.raw_requirements);
  const requirement = string(rawInput.text || rawRequirements.text, "Untitled delivery requirement");
  const meta = runStatusMeta(run.status);
  const pendingGateName = STATUS_TO_GATE[run.status];
  const config = record(state.config);
  const implementation = record(state.implementation);
  const qa = record(state.qa_result);
  const release = record(state.release_result || state.build_deploy_result);
  const tests = list(state.test_cases);
  const firstEvent = entries[0]?.timestamp;
  const changeUrl = string(implementation.change_url || implementation.pr_url, "");

  return (
    <main>
      <Link href="/runs" className="back-link">← Delivery runs</Link>

      <section className="run-hero">
        <div className="run-hero-copy">
          <div className="run-hero-meta"><StatusBadge status={run.status} /><span className="run-hero-id">RUN {runId.slice(0, 8).toUpperCase()}</span>{firstEvent && <span className="muted">Started {new Date(firstEvent).toLocaleString()}</span>}</div>
          <h1>{requirement}</h1>
        </div>
        {changeUrl && <a href={changeUrl} target="_blank" rel="noreferrer" className="button-link secondary">Open change ↗</a>}
      </section>

      <PipelineTimeline status={run.status} completedNodes={completedNodes} />

      <div className="run-layout">
        <div className="run-main">
          {meta.tone === "crit" && (
            <div className="notice crit" role="alert">
              <h3>The run ended in the {meta.stage} phase</h3>
              <p>{meta.label}. Review the phase evidence and audit record below before deciding whether the requirement or implementation should be revised.</p>
            </div>
          )}

          {run.pending_dispatch?.state === "pending" && (
            <DispatchWaitingPanel dispatch={run.pending_dispatch} onNudge={async () => { await nudgeDispatch(runId); await refreshAll(); }} />
          )}

          {run.pending_gate && pendingGateName && (
            <GateApprovalPanel gateName={pendingGateName} payload={run.pending_gate} onDecide={(approved, feedback) => onDecide(pendingGateName, approved, feedback)} pending={decisionPending} />
          )}
          {decisionError && <div className="notice crit" role="alert"><h3>The decision was not recorded</h3><p>{decisionError}</p></div>}

          <EvidenceSummary state={state} />
          <AuditLogView entries={entries} />
        </div>

        <aside className="run-aside">
          <section className="panel">
            <div className="panel-head"><div><h2>Run controls</h2><p>Resolved policy and evidence counters.</p></div></div>
            <div className="panel-body run-facts">
              <div className="run-fact"><span>Current phase</span><strong>{meta.stage}</strong></div>
              <div className="run-fact"><span>Waiting on</span><strong>{meta.waitingOn === "none" ? "No action" : meta.waitingOn}</strong></div>
              <div className="run-fact"><span>Approval policy</span><strong>{config.auto_approve_gates ? "Auto-approved" : "Human gated"}</strong></div>
              <div className="run-fact"><span>Generated tests</span><strong>{tests.length}</strong></div>
              <div className="run-fact"><span>Graph assertions</span><strong>{String(state.graph_edges_written ?? 0)}</strong></div>
              <div className="run-fact"><span>Audit events</span><strong>{entries.filter((entry) => entry.phase === "after").length}</strong></div>
            </div>
          </section>

          <section className="panel">
            <div className="panel-head"><div><h2>Delivery artifacts</h2><p>Links and revisions emitted by implementation, QA and release.</p></div></div>
            <div className="panel-body evidence-list">
              <div className="evidence-item"><span>Implementation agent</span><strong>{string(implementation.agent)}</strong></div>
              <div className="evidence-item"><span>Branch</span><strong><code>{string(implementation.branch)}</code></strong></div>
              <div className="evidence-item"><span>QA outcome</span><strong>{string(qa.state || qa.outcome || qa.feedback)}</strong></div>
              <div className="evidence-item"><span>Release target</span><strong>{string(release.environment || release.target)}</strong></div>
            </div>
          </section>
        </aside>
      </div>
    </main>
  );
}
