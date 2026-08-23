"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { createRun } from "@/lib/api";

export default function NewRunPage() {
  const router = useRouter();
  const [text, setText] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!text.trim()) return;
    setSubmitting(true);
    setError(null);
    try {
      const { run_id } = await createRun(text);
      router.push(`/runs/${run_id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setSubmitting(false);
    }
  }

  return (
    <main>
      <h1>Agentic SDLC Pipeline Accelerator</h1>
      <p className="muted">
        Scaffolding-phase demo — not production. Submit a requirement to watch it flow through a
        governed pipeline with human approval at every phase boundary.
      </p>

      <form className="card" onSubmit={onSubmit}>
        <label htmlFor="requirement" style={{ display: "block", marginBottom: "0.5rem" }}>
          Requirement
        </label>
        <textarea
          id="requirement"
          rows={5}
          placeholder="As a user, I want to reset my password..."
          value={text}
          onChange={(e) => setText(e.target.value)}
          disabled={submitting}
        />
        <div style={{ marginTop: "0.75rem" }}>
          <button type="submit" disabled={submitting || !text.trim()}>
            {submitting ? "Starting..." : "Start pipeline run"}
          </button>
        </div>
        {error && (
          <p style={{ color: "var(--danger)", marginTop: "0.75rem" }}>{error}</p>
        )}
      </form>

      <p>
        <a href="/runs">View past runs →</a>
      </p>
    </main>
  );
}
