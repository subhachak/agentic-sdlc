"use client";

import { useEffect, useRef, useState } from "react";
import { approveGate, eventsUrl, getAuditTrail, getRun, nudgeDispatch } from "@/lib/api";
import type { AuditEntry, RunDetail, StreamedAuditEvent } from "@/lib/types";
import PipelineTimeline from "@/components/pipeline-timeline";
import DispatchWaitingPanel from "@/components/dispatch-waiting-panel";
import GateApprovalPanel from "@/components/gate-approval-panel";
import AuditLogView from "@/components/audit-log-view";

const STATUS_TO_GATE: Record<string, string> = {
  awaiting_gate_1: "gate_1",
  awaiting_gate_2: "gate_2",
  awaiting_gate_3: "gate_3",
};

export default function RunView({ runId }: { runId: string }) {
  const [run, setRun] = useState<RunDetail | null>(null);
  const [entries, setEntries] = useState<AuditEntry[]>([]);
  const [hitlPending, setHitlPending] = useState(false);
  const [hitlError, setHitlError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const sourceRef = useRef<EventSource | null>(null);

  async function refreshRun() {
    try {
      const detail = await getRun(runId);
      setRun(detail);
    } catch {
      // transient — the next poll or SSE event will retry
    }
  }

  useEffect(() => {
    void refreshRun();
    void getAuditTrail(runId).then(setEntries);

    const source = new EventSource(eventsUrl(runId));
    sourceRef.current = source;

    source.addEventListener("audit", (evt) => {
      const parsed = JSON.parse((evt as MessageEvent).data) as StreamedAuditEvent;
      setEntries((prev) => [
        ...prev,
        {
          node_name: parsed.node_name,
          phase: parsed.phase,
          input_summary: {},
          output_summary: parsed.output_summary,
          confidence_score: null,
          confirmed: parsed.confirmed,
          human_decision: parsed.human_decision,
          timestamp: parsed.timestamp,
        },
      ]);
      // A gate's "before" phase is exactly when the run pauses (or, for
      // auto-approved runs, was momentarily reached) — refresh run detail so
      // the pending-gate payload and status stay current.
      if (parsed.phase === "before" && parsed.node_name.startsWith("gate_")) {
        void refreshRun();
      }
      if (parsed.node_name === "build_deploy_stub" && parsed.phase === "after") {
        void refreshRun();
      }
    });

    source.addEventListener("done", () => {
      setDone(true);
      void refreshRun();
      source.close();
    });

    source.onerror = () => {
      // EventSource retries connections on its own; nothing to do here.
    };

    return () => {
      source.close();
      sourceRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId]);

  async function onDecide(gateName: string, approved: boolean, feedback?: string) {
    setHitlPending(true);
    setHitlError(null);
    try {
      await approveGate(runId, gateName, approved, feedback);
      await refreshRun();
    } catch (err) {
      setHitlError(err instanceof Error ? err.message : String(err));
    } finally {
      setHitlPending(false);
    }
  }

  if (!run) {
    return (
      <main>
        <p className="muted">Loading run...</p>
      </main>
    );
  }

  const completedNodes = new Set(entries.filter((e) => e.phase === "after").map((e) => e.node_name));

  const pendingGateName = STATUS_TO_GATE[run.status];

  return (
    <main>
      <p>
        <a href="/runs">← All runs</a>
      </p>
      <h1>Run {runId.slice(0, 8)}</h1>

      <PipelineTimeline status={run.status} completedNodes={completedNodes} />

      {run.pending_dispatch && run.pending_dispatch.state === "pending" && !done && (
        <DispatchWaitingPanel
          dispatch={run.pending_dispatch}
          onNudge={async () => {
            await nudgeDispatch(runId);
            await refreshRun();
          }}
        />
      )}

      {run.pending_gate && pendingGateName && !done && (
        <GateApprovalPanel
          gateName={pendingGateName}
          payload={run.pending_gate}
          onDecide={(approved, feedback) => onDecide(pendingGateName, approved, feedback)}
          pending={hitlPending}
        />
      )}
      {hitlError && <p style={{ color: "var(--danger)" }}>{hitlError}</p>}

      <AuditLogView entries={entries} />
    </main>
  );
}
