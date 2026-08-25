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
    <main className="narrow">
      <div className="page-head">
        <h1>Start a run</h1>
        <p>
          Describe what should change, in the words you would use with a colleague. Agents
          propose, deterministic gates decide, and you approve at every phase boundary.
        </p>
      </div>

      <form onSubmit={onSubmit}>
        <section className="panel">
          <div className="panel-head">
            <div>
              <h2>Requirement</h2>
              <p>Plain English. The platform derives the acceptance criteria from it.</p>
            </div>
          </div>
          <div className="panel-body">
            <textarea
              id="requirement"
              rows={6}
              placeholder="Add a status filter to the claims list, so an adjuster can see only open claims."
              value={text}
              onChange={(e) => setText(e.target.value)}
              disabled={submitting}
              autoFocus
            />
          </div>
          <div className="row" style={{ borderBottom: 0 }}>
            <div className="row-main">
              <div className="row-help" style={{ color: error ? "var(--crit)" : undefined }}>
                {error ?? "You will be asked to approve before anything is written."}
              </div>
            </div>
            <div className="row-end">
              <button type="submit" disabled={submitting || !text.trim()}>
                {submitting ? "Starting…" : "Start run"}
              </button>
            </div>
          </div>
        </section>
      </form>
    </main>
  );
}
