"use client";

import { useCallback, useEffect, useState } from "react";
import {
  hydrationStatus,
  listRepositories,
  syncGraph,
  type HydrationStatus,
  type RepositoryList,
  type ScopeCandidate,
  type SyncResult,
  type SyncStep,
} from "@/lib/api";

/**
 * The whole of setup that is an action rather than a value.
 *
 * One control: choose a repository, press Sync. Everything the console used
 * to ask for around it — the ref, the scope, whether this is a first index
 * or a delta, whether to also build retrieval and export — is derivable, and
 * asking was how they came to disagree with each other.
 *
 * The one question that survives is a real one: a repository with more than
 * one deployable unit cannot be scoped without being told which, and getting
 * that wrong points a QA run at an app nobody changed.
 */

const TONE: Record<SyncStep["status"], string> = {
  ok: "ok",
  failed: "crit",
  needs_choice: "warn",
  skipped: "idle",
};

const STEP_TITLE: Record<SyncStep["step"], string> = {
  index: "Read the repository",
  retrieval: "Ground the design agent",
  export: "Hand off to the execution plane",
};

export default function RepositoryPanel({ onChanged }: { onChanged?: () => void }) {
  const [status, setStatus] = useState<HydrationStatus | null>(null);
  const [catalogue, setCatalogue] = useState<RepositoryList | null>(null);
  const [repo, setRepo] = useState("");
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
        setRepo((current) => current || list.current || list.repositories[0]?.full_name || "");
      } catch (err) {
        setCatalogue({
          available: false,
          reason: err instanceof Error ? err.message : String(err),
          repositories: [],
        });
      }
    })();
  }, [load]);

  async function sync(scope?: string | null) {
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const next = await syncGraph(repo, scope ?? null);
      setResult(next);
      setChoices(next.steps.find((s) => s.status === "needs_choice")?.candidates ?? null);
      await load();
      onChanged?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  const selected = catalogue?.repositories.find((r) => r.full_name === repo);
  const canList = Boolean(catalogue?.available && catalogue.repositories.length);
  const ready = status?.hydrated;

  return (
    <section className="panel">
      <div className="panel-head">
        <div>
          <h2>Repository</h2>
          <p>
            One button for the first index and every update after it. It reads the
            repository, grounds the design agent in it, and writes the copy the execution
            plane tests against — reporting what moved rather than rebuilding silently.
          </p>
        </div>
        <div className="panel-head-end">
          <span className={`pill ${busy ? "busy" : ready ? "ok" : "warn"}`}>
            {busy ? "Syncing" : ready ? "Ready" : "Incomplete"}
          </span>
        </div>
      </div>

      <div className="row">
        <div className="row-main">
          <div className="row-label">
            <label htmlFor="repo-select">Which repository</label>
          </div>
          <div className="row-help">
            {canList
              ? `${catalogue!.repositories.length} visible to the configured credentials`
              : catalogue?.reason || "Loading…"}
            {selected && (
              <>
                {" · branch "}
                <code>{selected.default_branch}</code>
              </>
            )}
          </div>
        </div>
        <div className="row-end" style={{ flex: "1 1 22rem", justifyContent: "flex-end" }}>
          {canList ? (
            <select
              id="repo-select"
              value={repo}
              className="grow"
              onChange={(e) => {
                setRepo(e.target.value);
                // A different repository has different subtrees, so a scope
                // chosen for the last one is not an answer for this one.
                setChoices(null);
                setResult(null);
              }}
            >
              {catalogue!.repositories.map((r) => (
                <option key={r.full_name} value={r.full_name}>
                  {r.full_name}
                  {r.private ? " · private" : ""}
                  {r.full_name === catalogue!.current ? " · indexed" : ""}
                </option>
              ))}
            </select>
          ) : (
            <input
              id="repo-select"
              type="text"
              className="grow"
              placeholder="owner/name"
              value={repo}
              onChange={(e) => setRepo(e.target.value)}
            />
          )}
          <button onClick={() => void sync()} disabled={busy || !repo.trim()}>
            {busy ? "Syncing…" : "Sync"}
          </button>
        </div>
      </div>

      {choices && (
        <div style={{ padding: "var(--s4) var(--s5)", borderBottom: "1px solid var(--line)" }}>
          <div className="notice warn" style={{ marginBottom: 0 }}>
            <h3>Which part does the execution plane test?</h3>
            <p>
              This repository holds more than one separately buildable unit. Scoping is not
              about size: a QA run testing one app should not be told a change reaches
              another.
            </p>
            <div className="inline" style={{ marginTop: "var(--s3)" }}>
              {choices.map((c) => (
                <button
                  key={c.path || "__all__"}
                  className="ghost"
                  disabled={busy}
                  onClick={() => void sync(c.path)}
                >
                  {c.label}
                  <span className="muted" style={{ marginLeft: 6 }}>
                    {c.files} files
                  </span>
                </button>
              ))}
            </div>
          </div>
        </div>
      )}

      <div className="panel-body flush">
        {(result?.steps ?? []).map((step) => (
          <div className="row" key={step.step}>
            <div className="row-main">
              <div className="row-label">{STEP_TITLE[step.step]}</div>
              <div className="row-help">{step.summary}</div>
            </div>
            <div className="row-end">
              <span className={`pill ${TONE[step.status]}`}>
                {step.status === "needs_choice" ? "Needs a choice" : step.status}
              </span>
            </div>
          </div>
        ))}

        {!result &&
          (status?.steps ?? []).map((step) => (
            <div className="row" key={step.id}>
              <div className="row-main">
                <div className="row-label">{step.title}</div>
                <div className="row-help">{step.detail}</div>
                {step.quality && !step.quality.sufficient && (
                  <div className="row-help" style={{ color: "var(--crit)" }}>
                    Only {(step.quality.internal_capture_rate * 100).toFixed(1)}% of internal
                    imports resolved. Below 80% the design phase refuses, because an impact
                    set derived from this many missing edges cannot be trusted.
                  </div>
                )}
              </div>
              <div className="row-end">
                <span className={`pill ${step.ready ? "ok" : "warn"}`}>
                  {step.ready ? "Ready" : "Not yet"}
                </span>
              </div>
            </div>
          ))}
      </div>

      {error && (
        <div className="panel-body" style={{ borderTop: "1px solid var(--line)" }}>
          <p style={{ margin: 0, color: "var(--crit)", fontSize: "0.875rem" }}>{error}</p>
        </div>
      )}
    </section>
  );
}
