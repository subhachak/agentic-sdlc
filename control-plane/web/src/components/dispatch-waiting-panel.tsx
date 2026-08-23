"use client";

import { useEffect, useState } from "react";
import type { PendingDispatch } from "@/lib/types";

function elapsed(fromIso: string): string {
  const seconds = Math.max(0, Math.floor((Date.now() - new Date(fromIso).getTime()) / 1000));
  const minutes = Math.floor(seconds / 60);
  return minutes > 0 ? `${minutes}m ${seconds % 60}s` : `${seconds}s`;
}

/**
 * Shown instead of the gate panel while a run waits on a remote execution.
 * There is deliberately no Approve button: nothing a person clicks here
 * unblocks the run, and offering one would misrepresent who is in control.
 */
export default function DispatchWaitingPanel({
  dispatch,
  onNudge,
}: {
  dispatch: PendingDispatch;
  onNudge: () => void;
}) {
  const [, tick] = useState(0);

  useEffect(() => {
    const id = setInterval(() => tick((n) => n + 1), 1000);
    return () => clearInterval(id);
  }, []);

  const deadline = new Date(dispatch.deadline_at);

  return (
    <div className="card">
      <h3 style={{ marginTop: 0 }}>
        Running {dispatch.phase.toUpperCase()} on {dispatch.provider}
      </h3>
      <p className="muted" style={{ marginTop: 0 }}>
        Waiting {elapsed(dispatch.started_at)} — gives up at {deadline.toLocaleTimeString()}.
        No approval is needed; the run continues on its own when the job reports.
      </p>
      <div style={{ display: "flex", gap: "0.5rem", marginTop: "0.6rem", alignItems: "center" }}>
        {dispatch.external_url && (
          <a href={dispatch.external_url} target="_blank" rel="noreferrer">
            View the run →
          </a>
        )}
        <button onClick={onNudge}>Check now</button>
      </div>
    </div>
  );
}
