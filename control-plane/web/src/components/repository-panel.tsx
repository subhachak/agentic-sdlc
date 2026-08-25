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

const STEP_TITLE: Record<SyncStep["step"], string> = {
  index: "Architecture index",
  retrieval: "Agent grounding",
  export: "QA execution handoff",
};

const STEP_DETAIL: Record<SyncStep["step"], string> = {
  index: "Parse modules, imports and HTTP contracts",
  retrieval: "Build revision-pinned design context",
  export: "Publish scoped evidence for CI",
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
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }, []);

  useEffect(() => {
    void load();
    void listRepositories()
      .then((list) => {
        setCatalogue(list);
        setRepo((current) => current || list.current || list.repositories[0]?.full_name || "");
      })
      .catch((reason) => setCatalogue({ available: false, reason: reason instanceof Error ? reason.message : String(reason), repositories: [] }));
  }, [load]);

  const selected = catalogue?.repositories.find((item) => item.full_name === repo);
  const canList = Boolean(catalogue?.available && catalogue.repositories.length);

  async function sync(scope?: string | null) {
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const next = await syncGraph(repo, scope ?? null, selected?.default_branch ?? null);
      setResult(next);
      setChoices(next.steps.find((step) => step.status === "needs_choice")?.candidates ?? null);
      await load();
      onChanged?.();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  }

  const steps = result?.steps ?? status?.steps.map((step) => ({
    step: step.id as SyncStep["step"],
    status: step.ready ? "ok" as const : "skipped" as const,
    summary: step.detail,
  })) ?? [];

  return (
    <section className="panel elevated">
      <div className="panel-head">
        <div>
          <h2>Repository and architecture context</h2>
          <p>One sync keeps the architecture graph, agent grounding and QA handoff on the same revision.</p>
        </div>
        <div className="panel-head-end"><span className={`pill ${busy ? "busy" : status?.hydrated ? "ok" : "warn"}`}>{busy ? "Synchronizing" : status?.hydrated ? "Ready" : "Action required"}</span></div>
      </div>
      <div className="panel-body">
        <div className="repository-select-row">
          <label>
            <span className="field-label">Source repository</span>
            {canList ? (
              <select value={repo} onChange={(event) => { setRepo(event.target.value); setChoices(null); setResult(null); }}>
                {catalogue!.repositories.map((item) => <option value={item.full_name} key={item.full_name}>{item.full_name}{item.private ? " · private" : ""}{item.full_name === catalogue!.current ? " · indexed" : ""}</option>)}
              </select>
            ) : (
              <input type="text" value={repo} placeholder="owner/repository" onChange={(event) => setRepo(event.target.value)} />
            )}
            <span className="field-help">
              {selected ? `Default branch ${selected.default_branch} · updated ${new Date(selected.updated_at).toLocaleDateString()}` : catalogue?.reason || "Discovering repositories available to the configured source…"}
            </span>
          </label>
          <button type="button" disabled={busy || !repo.trim()} onClick={() => void sync()}>{busy ? "Synchronizing…" : status?.provenance.repo === repo ? "Sync latest revision" : "Connect and index"}</button>
        </div>

        {choices && (
          <div className="notice warn" style={{ marginTop: 16, marginBottom: 0 }}>
            <h3>Select the application this engagement tests</h3>
            <p>The repository contains multiple deployable units. This is the only scope decision the platform cannot infer safely.</p>
            <div className="scope-options">
              {choices.map((choice) => (
                <button type="button" key={choice.path || "__all__"} className="secondary scope-option" disabled={busy} onClick={() => void sync(choice.path)}>
                  <span><strong>{choice.label}</strong><small>{choice.files} files · {choice.marker}</small></span>
                </button>
              ))}
            </div>
          </div>
        )}
      </div>

      {steps.length > 0 && (
        <div className="sync-steps">
          {steps.map((step, index) => {
            const ready = step.status === "ok";
            return (
              <div className="sync-step" key={step.step}>
                <span className={`sync-step-index ${ready ? "" : "pending"}`}>{ready ? "✓" : `0${index + 1}`}</span>
                <strong>{STEP_TITLE[step.step]}</strong>
                <span>{step.summary || STEP_DETAIL[step.step]}</span>
              </div>
            );
          })}
        </div>
      )}

      {status?.provenance.commit_sha && (
        <div className="row">
          <div className="row-main"><div className="row-label">Current indexed revision</div><div className="row-help">Pinned evidence used by design and QA scope calculations.</div></div>
          <div className="row-end"><code>{status.provenance.commit_sha.slice(0, 12)}</code></div>
        </div>
      )}
      {error && <div className="notice crit" role="alert" style={{ margin: 16 }}><h3>Repository synchronization failed</h3><p>{error}</p></div>}
    </section>
  );
}
