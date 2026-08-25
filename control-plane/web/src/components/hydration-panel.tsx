"use client";

import { useCallback, useEffect, useState } from "react";
import {
  hydrationStatus,
  listRepositories,
  syncGraph,
  type HydrationStatus,
  type HydrationStep,
  type RepositoryList,
  type ScopeCandidate,
  type SyncResult,
  type SyncStep,
} from "@/lib/api";

/**
 * First-time setup, and every update after it.
 *
 * This was four buttons and three text boxes that had to agree with each
 * other — index, build retrieval, export, with a repository, a ref and a
 * scope typed in separately. Nothing enforced the order, nothing checked
 * that the fields matched, and the commonest mistake produced an error
 * naming a step that was not the problem.
 *
 * All of it is derivable. Which repositories exist is a question for the
 * credentials already configured. The ref is a property of the repository.
 * The scope is a property of the code that was just indexed. Whether this
 * is a first index or a delta is a question about the graph. So: pick a
 * repository, press one button, and answer a question only when there is a
 * genuine choice to make.
 *
 * The per-step state below is still shown, because "it worked" and "the
 * index worked and grounding read nothing" are different answers and the
 * second one used to be reported as success.
 */

const TONE: Record<string, string> = {
  ok: "var(--success)",
  failed: "var(--danger)",
  needs_choice: "var(--warning)",
  skipped: "var(--muted)",
};

function StepResult({ step }: { step: SyncStep }) {
  return (
    <li style={{ marginBottom: "0.4rem" }}>
      <span aria-hidden style={{ color: TONE[step.status], marginRight: "0.4rem" }}>
        {step.status === "ok" ? "●" : step.status === "skipped" ? "○" : "▲"}
      </span>
      <strong style={{ textTransform: "capitalize" }}>{step.step}</strong>
      <span className="sr-only">{step.status}</span> — {step.summary}
    </li>
  );
}

function StepState({ step }: { step: HydrationStep }) {
  const blocked = step.blocked_by !== null;
  const colour = step.ready ? "var(--success)" : blocked ? "var(--muted)" : "var(--warning)";
  return (
    <li style={{ marginBottom: "0.35rem" }}>
      <span aria-hidden style={{ color: colour, marginRight: "0.4rem" }}>
        {step.ready ? "●" : "○"}
      </span>
      <strong>{step.title}</strong>
      <span className="sr-only">{step.ready ? "ready" : "not ready"}</span>
      <span className="muted"> — {step.detail}</span>
      {step.quality && !step.quality.sufficient && (
        <div className="field-help" style={{ color: "var(--danger)" }}>
          Only {(step.quality.internal_capture_rate * 100).toFixed(1)}% of internal imports
          resolved. Below 80% the design phase refuses, because an impact set derived from this
          many missing edges cannot be trusted.
          {step.quality.most_missed.length > 0 && (
            <> Unresolved: {step.quality.most_missed.map(([spec]) => spec).join(", ")}</>
          )}
        </div>
      )}
    </li>
  );
}

export function HydrationPanel({ onChanged }: { onChanged?: () => void }) {
  const [status, setStatus] = useState<HydrationStatus | null>(null);
  const [catalogue, setCatalogue] = useState<RepositoryList | null>(null);
  const [repo, setRepo] = useState("");
  const [scope, setScope] = useState<string | null>(null);
  const [choices, setChoices] = useState<ScopeCandidate[] | null>(null);
  const [result, setResult] = useState<SyncResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const next = await hydrationStatus();
      setStatus(next);
      setRepo((current) => current || next.provenance.repo || "");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, []);

  useEffect(() => {
    void load();
    void (async () => {
      try {
        const list = await listRepositories();
        setCatalogue(list);
        // Whatever is already indexed wins; otherwise the most recently
        // pushed, which is nearly always the one someone is here about.
        setRepo((current) => current || list.current || list.repositories[0]?.full_name || "");
      } catch (err) {
        setCatalogue({ available: false, reason: String(err), repositories: [] });
      }
    })();
  }, [load]);

  async function sync(withScope?: string | null) {
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const next = await syncGraph(repo, withScope ?? scope);
      setResult(next);
      const choice = next.steps.find((s) => s.status === "needs_choice");
      setChoices(choice?.candidates ?? null);
      await load();
      onChanged?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  const selected = catalogue?.repositories.find((r) => r.full_name === repo);
  const canList = catalogue?.available && catalogue.repositories.length > 0;

  return (
    <div className="card">
      <h2 style={{ marginTop: 0, fontSize: "1rem" }}>
        Setup{" "}
        {status && (
          <span
            className="muted"
            style={{ fontWeight: 400, color: status.hydrated ? "var(--success)" : "var(--warning)" }}
          >
            — {status.hydrated ? "hydrated" : "incomplete"}
          </span>
        )}
      </h2>
      <p className="field-help" style={{ marginTop: "-0.4rem" }}>
        Choose a repository and press Sync. The same button does the first index and every update
        after it — it reads the repository, grounds the design agent, and writes the copy the
        execution plane tests against, reporting what changed rather than rebuilding silently.
      </p>

      <div className="field">
        <div>
          <div className="field-label">Repository</div>
          <div className="field-help">
            {canList
              ? `${catalogue!.repositories.length} available to the configured credentials`
              : catalogue?.reason || "loading..."}
          </div>
        </div>
        <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", flex: "1 1 18rem" }}>
          {canList ? (
            <select
              value={repo}
              onChange={(e) => {
                setRepo(e.target.value);
                // A different repository has different subtrees, so a scope
                // chosen for the last one is not an answer for this one.
                setScope(null);
                setChoices(null);
                setResult(null);
              }}
              style={{ flex: "1 1 14rem" }}
            >
              {catalogue!.repositories.map((r) => (
                <option key={r.full_name} value={r.full_name}>
                  {r.full_name}
                  {r.private ? " (private)" : ""}
                  {r.full_name === catalogue!.current ? " — indexed" : ""}
                </option>
              ))}
            </select>
          ) : (
            <input
              type="text"
              placeholder="owner/name"
              value={repo}
              onChange={(e) => setRepo(e.target.value)}
              style={{ flex: "1 1 14rem" }}
            />
          )}
          <button onClick={() => void sync()} disabled={busy || !repo.trim()}>
            {busy ? "Syncing..." : "Sync"}
          </button>
        </div>
      </div>

      {selected && (
        <p className="field-help" style={{ marginTop: "-0.5rem" }}>
          Branch <code>{selected.default_branch}</code>
          {selected.description ? ` · ${selected.description}` : ""}
        </p>
      )}

      {choices && (
        <div className="card notice" style={{ marginTop: "0.75rem" }}>
          <strong>Which part does the execution plane test?</strong>
          <p className="field-help" style={{ margin: "0.35rem 0 0.6rem" }}>
            This repository has more than one separately buildable unit. Scoping is not only about
            size: a QA run testing one app should not be told a change reaches another.
          </p>
          <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
            {choices.map((c) => (
              <button
                key={c.path || "__all__"}
                onClick={() => {
                  setScope(c.path);
                  void sync(c.path);
                }}
                disabled={busy}
              >
                {c.label}{" "}
                {/* Not .muted — that colour is chosen against the page
                    background and is close to unreadable on a filled
                    button. */}
                <span style={{ opacity: 0.75 }}>({c.files} files)</span>
              </button>
            ))}
          </div>
        </div>
      )}

      {result && (
        <ul style={{ margin: "0.75rem 0 0", paddingLeft: "1.1rem", listStyle: "none" }}>
          {result.steps.map((s) => (
            <StepResult key={s.step} step={s} />
          ))}
        </ul>
      )}

      {status && !result && (
        <ul style={{ margin: "0.75rem 0 0", paddingLeft: "1.1rem", listStyle: "none" }}>
          {status.steps.map((s) => (
            <StepState key={s.id} step={s} />
          ))}
        </ul>
      )}

      {error && (
        <p style={{ color: "var(--danger)", marginBottom: 0, marginTop: "0.75rem" }}>{error}</p>
      )}
    </div>
  );
}
