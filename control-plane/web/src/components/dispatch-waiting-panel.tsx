"use client";

import { useEffect, useState } from "react";
import type { PendingDispatch } from "@/lib/types";

function elapsed(fromIso: string) {
  const seconds = Math.max(0, Math.floor((Date.now() - new Date(fromIso).getTime()) / 1000));
  const minutes = Math.floor(seconds / 60);
  return minutes ? `${minutes}m ${seconds % 60}s` : `${seconds}s`;
}

export default function DispatchWaitingPanel({ dispatch, onNudge }: { dispatch: PendingDispatch; onNudge: () => void }) {
  const [, tick] = useState(0);
  const [checking, setChecking] = useState(false);
  useEffect(() => {
    const timer = setInterval(() => tick((value) => value + 1), 1000);
    return () => clearInterval(timer);
  }, []);

  return (
    <section className="panel dispatch-panel" aria-live="polite">
      <div className="dispatch-heading">
        <span className="dispatch-spinner" aria-hidden />
        <div><h2>{dispatch.phase.toUpperCase()} is running on {dispatch.provider}</h2><span className="pill busy">Machine work</span></div>
      </div>
      <p>Running for {elapsed(dispatch.started_at)}. The workflow continues automatically when CI reports; no human approval is needed here.</p>
      <div className="dispatch-actions">
        {dispatch.external_url && <a href={dispatch.external_url} target="_blank" rel="noreferrer" className="button-link secondary">Open external job ↗</a>}
        <button type="button" className="quiet" disabled={checking} onClick={async () => { setChecking(true); try { await onNudge(); } finally { setChecking(false); } }}>{checking ? "Checking…" : "Check now"}</button>
      </div>
    </section>
  );
}
