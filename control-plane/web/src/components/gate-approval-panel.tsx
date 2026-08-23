"use client";

import { useState } from "react";

export default function GateApprovalPanel({
  gateName,
  payload,
  onDecide,
  pending,
}: {
  gateName: string;
  payload: Record<string, unknown>;
  onDecide: (approved: boolean, feedback?: string) => void;
  pending: boolean;
}) {
  const [feedback, setFeedback] = useState("");

  return (
    <div className="card">
      <h3 style={{ marginTop: 0 }}>Awaiting decision — {gateName.replaceAll("_", " ")}</h3>
      <pre>{JSON.stringify(payload, null, 2)}</pre>
      <textarea
        placeholder="Optional feedback"
        value={feedback}
        onChange={(e) => setFeedback(e.target.value)}
        rows={2}
        disabled={pending}
        style={{ marginTop: "0.6rem" }}
      />
      <div style={{ display: "flex", gap: "0.5rem", marginTop: "0.6rem" }}>
        <button onClick={() => onDecide(true, feedback || undefined)} disabled={pending}>
          Approve
        </button>
        <button className="danger" onClick={() => onDecide(false, feedback || undefined)} disabled={pending}>
          Reject
        </button>
      </div>
    </div>
  );
}
