"use client";

import { useState } from "react";

const GATES: Record<string, { title: string; description: string }> = {
  gate_1: {
    title: "Approve the requirement baseline",
    description: "Confirm that the interpreted outcome is clear enough to design against.",
  },
  gate_2: {
    title: "Approve the proposed design",
    description: "Review intended scope, structural impact, exclusions and implementation risks.",
  },
  gate_3: {
    title: "Approve release evidence",
    description: "Confirm that QA outcomes and observed evidence satisfy the release policy.",
  },
};

function label(value: string) {
  return value.replaceAll("_", " ").replace(/\b\w/g, (character) => character.toUpperCase());
}

function shortValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "Not provided";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "string" || typeof value === "number") return String(value);
  if (Array.isArray(value)) return `${value.length} item${value.length === 1 ? "" : "s"}`;
  return `${Object.keys(value as Record<string, unknown>).length} details`;
}

function PayloadSection({ name, value }: { name: string; value: unknown }) {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    const entries = Object.entries(value as Record<string, unknown>);
    return (
      <section className="payload-section">
        <strong>{label(name)}</strong>
        <div className="payload-grid">
          {entries.slice(0, 10).map(([key, item]) => (
            <div className="payload-field" key={key}>
              <span>{label(key)}</span>
              <strong>{shortValue(item)}</strong>
            </div>
          ))}
        </div>
      </section>
    );
  }
  if (Array.isArray(value)) {
    return (
      <section className="payload-section">
        <strong>{label(name)} · {value.length}</strong>
        <div className="stack">
          {value.slice(0, 6).map((item, index) => (
            <div className="payload-value" key={index}>{typeof item === "string" ? item : JSON.stringify(item)}</div>
          ))}
          {value.length > 6 && <span className="muted">+ {value.length - 6} more in technical evidence</span>}
        </div>
      </section>
    );
  }
  return <section className="payload-section"><strong>{label(name)}</strong><div className="payload-value">{shortValue(value)}</div></section>;
}

export default function GateApprovalPanel({ gateName, payload, onDecide, pending }: {
  gateName: string;
  payload: Record<string, unknown>;
  onDecide: (approved: boolean, feedback?: string) => void;
  pending: boolean;
}) {
  const [feedback, setFeedback] = useState("");
  const copy = GATES[gateName] ?? { title: "Approval required", description: "Review the governed evidence before the run continues." };
  const evidence = Object.entries(payload).filter(([key]) => key !== "type");

  return (
    <section className="panel decision-panel">
      <div className="decision-banner">
        <span className="decision-mark" aria-hidden>!</span>
        <div><h2>{copy.title}</h2><p>{copy.description}</p></div>
      </div>

      <div className="payload-sections">
        {evidence.length ? evidence.map(([key, value]) => <PayloadSection key={key} name={key} value={value} />) : <p className="muted">No structured evidence was attached to this decision.</p>}
      </div>

      <details className="disclosure">
        <summary>Technical evidence</summary>
        <div className="panel-body"><pre>{JSON.stringify(payload, null, 2)}</pre></div>
      </details>

      <div className="decision-form">
        <label htmlFor={`decision-note-${gateName}`} className="field-label">Decision note <span className="muted">· required when requesting changes</span></label>
        <textarea id={`decision-note-${gateName}`} rows={3} placeholder="Capture an exception, concern or the change required…" value={feedback} onChange={(event) => setFeedback(event.target.value)} disabled={pending} />
        <div className="decision-actions">
          <button type="button" className="danger-secondary" onClick={() => onDecide(false, feedback.trim())} disabled={pending || !feedback.trim()}>{pending ? "Recording…" : "Request changes"}</button>
          <button type="button" onClick={() => onDecide(true, feedback.trim() || undefined)} disabled={pending}>{pending ? "Recording…" : "Approve and continue"}</button>
        </div>
      </div>
    </section>
  );
}
