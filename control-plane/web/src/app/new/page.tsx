"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { createRun, getDashboard } from "@/lib/api";
import type { DashboardData } from "@/lib/types";

const EXAMPLES = [
  { label: "Customer workflow", text: "Allow a customer to reset a forgotten password securely, including expired-link and invalid-account handling." },
  { label: "Operations change", text: "Add a status filter to the claims queue so adjusters can focus on open and escalated claims." },
  { label: "API behavior", text: "Expose claim payment history through the customer API without returning internal reconciliation fields." },
];

export default function NewRunPage() {
  const router = useRouter();
  const [text, setText] = useState("");
  const [context, setContext] = useState<DashboardData | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void getDashboard().then(setContext).catch((reason) => setError(reason instanceof Error ? reason.message : String(reason)));
  }, []);

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (!text.trim() || context?.hydration.hydrated === false) return;
    setSubmitting(true);
    setError(null);
    try {
      const { run_id } = await createRun(text.trim());
      router.push(`/runs/${run_id}`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
      setSubmitting(false);
    }
  }

  const blocked = context !== null && !context.hydration.hydrated;

  return (
    <main className="narrow">
      <Link href="/runs" className="back-link">← Delivery runs</Link>
      <div className="page-head">
        <div className="page-head-copy">
          <span className="eyebrow">New governed workflow</span>
          <h1>What outcome should the team deliver?</h1>
          <p>One clear requirement is the only mandatory input. Repository, branch, policy and execution context are inherited automatically.</p>
        </div>
      </div>

      {blocked && (
        <div className="notice warn" role="alert">
          <h3>This engagement is not ready to run</h3>
          <p>Complete repository indexing and the QA handoff first. <Link href="/setup">Open Administration</Link></p>
        </div>
      )}

      <div className="new-run-layout">
        <form onSubmit={onSubmit} className="requirement-editor">
          <section className="panel elevated">
            <div className="panel-head">
              <div><h2>Delivery requirement</h2><p>Describe the user or business outcome. The platform derives acceptance criteria and asks only when ambiguity matters.</p></div>
              <span className="pill info">Only required input</span>
            </div>
            <label htmlFor="requirement" className="sr-only">Delivery requirement</label>
            <textarea
              id="requirement"
              rows={8}
              placeholder="For example: Allow an adjuster to filter the claims queue by status, so urgent open claims can be handled first."
              value={text}
              onChange={(event) => setText(event.target.value)}
              disabled={submitting || blocked}
              autoFocus
            />
            <div className="editor-footer">
              <span className="editor-hint" aria-live="polite">
                {error ? <span style={{ color: "var(--danger)" }}>{error}</span> : text.trim() ? `${text.trim().length} characters · context will be attached automatically` : "You will review the interpreted requirement before any code is changed."}
              </span>
              <button type="submit" disabled={submitting || blocked || !text.trim()}>
                {submitting ? "Starting workflow…" : "Start governed run"}
              </button>
            </div>
          </section>

          <section className="panel">
            <div className="panel-body">
              <span className="field-label">Use an example as a starting point</span>
              <div className="template-list">
                {EXAMPLES.map((example) => (
                  <button key={example.label} type="button" className="template-chip" onClick={() => setText(example.text)} disabled={submitting || blocked}>
                    {example.label}
                  </button>
                ))}
              </div>
            </div>
          </section>
        </form>

        <aside>
          <section className="panel">
            <div className="panel-head"><div><h2>Inherited run context</h2><p>Read-only values resolved from the active engagement.</p></div></div>
            <div className="panel-body auto-context">
              <div className="auto-context-row"><span>Engagement</span><strong>{context?.project || "Loading…"}</strong></div>
              <div className="auto-context-row"><span>Repository</span><code>{context?.engagement.indexed_repo || "—"}</code></div>
              <div className="auto-context-row"><span>Base branch</span><code>{context?.engagement.target_ref || context?.engagement.indexed_ref || "—"}</code></div>
              <div className="auto-context-row"><span>Environment</span><strong>{context?.engagement.environment || "—"}</strong></div>
              <div className="auto-context-row"><span>Execution</span><strong>{context?.platform.execution_target || "—"}</strong></div>
              <div className="auto-context-row"><span>Approval policy</span><strong>{context?.platform.gates === "human" ? "Human gated" : "Auto-approved"}</strong></div>
            </div>
          </section>

          <section className="panel">
            <div className="panel-head"><div><h2>What happens next</h2></div></div>
            <div className="panel-body automation-list">
              <div className="automation-item"><span className="automation-number">01</span><span><strong>Interpret and clarify</strong><span>Derive structured requirements and surface meaningful ambiguity.</span></span></div>
              <div className="automation-item"><span className="automation-number">02</span><span><strong>Design against evidence</strong><span>Use repository context and calculate structural impact.</span></span></div>
              <div className="automation-item"><span className="automation-number">03</span><span><strong>Implement and assure</strong><span>Generate tests, execute QA and retain decision evidence.</span></span></div>
            </div>
          </section>
        </aside>
      </div>
    </main>
  );
}
