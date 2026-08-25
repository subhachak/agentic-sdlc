"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import StatusBadge, { runStatusMeta } from "@/components/status-badge";
import type { RunSummary } from "@/lib/types";

type View = "all" | "attention" | "active" | "completed" | "failed";

const VIEWS: { id: View; label: string }[] = [
  { id: "all", label: "All" },
  { id: "attention", label: "Needs attention" },
  { id: "active", label: "In progress" },
  { id: "completed", label: "Completed" },
  { id: "failed", label: "Failed" },
];

function belongs(run: RunSummary, view: View) {
  const meta = runStatusMeta(run.status);
  if (view === "all") return true;
  if (view === "attention") return meta.waitingOn === "human" || meta.tone === "crit";
  if (view === "active") return !meta.terminal && meta.waitingOn !== "human";
  if (view === "completed") return run.status === "completed";
  return meta.tone === "crit";
}

export default function RunList({ runs }: { runs: RunSummary[] }) {
  const [view, setView] = useState<View>("all");
  const [query, setQuery] = useState("");

  const filtered = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    return runs.filter((run) => {
      if (!belongs(run, view)) return false;
      if (!normalized) return true;
      return `${run.raw_requirement_text} ${run.run_id} ${run.status}`.toLowerCase().includes(normalized);
    });
  }, [query, runs, view]);

  const counts = useMemo(
    () => Object.fromEntries(VIEWS.map((item) => [item.id, runs.filter((run) => belongs(run, item.id)).length])),
    [runs]
  ) as Record<View, number>;

  return (
    <section className="panel elevated">
      <div className="toolbar">
        <div className="toolbar-group tabs" role="tablist" aria-label="Filter delivery runs">
          {VIEWS.map((item) => (
            <button
              key={item.id}
              type="button"
              className="tab-button"
              role="tab"
              aria-selected={view === item.id}
              onClick={() => setView(item.id)}
            >
              {item.label} · {counts[item.id]}
            </button>
          ))}
        </div>
        <div className="toolbar-group">
          <label className="search-control">
            <span className="sr-only">Search runs</span>
            <input
              type="search"
              placeholder="Search requirement or run ID"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
          </label>
          <span className="result-count">{filtered.length} shown</span>
        </div>
      </div>

      {filtered.length === 0 ? (
        <div className="empty-state">
          <span className="empty-state-mark">RUN</span>
          <h3>{runs.length === 0 ? "No delivery runs yet" : "No runs match this view"}</h3>
          <p>{runs.length === 0 ? "Start with one requirement; repository, policy and execution context are inferred." : "Change the status view or clear the search."}</p>
          {runs.length === 0 && <Link href="/new" className="button-link">Start the first run</Link>}
        </div>
      ) : (
        <>
          <div className="table-wrap run-table">
            <table>
              <thead>
                <tr><th>Requirement</th><th>Current stage</th><th>Status</th><th>Started</th><th aria-label="Open" /></tr>
              </thead>
              <tbody>
                {filtered.map((run) => {
                  const meta = runStatusMeta(run.status);
                  return (
                    <tr key={run.run_id}>
                      <td className="table-primary">
                        <Link className="table-link" href={`/runs/${run.run_id}`}>{run.raw_requirement_text || "Untitled requirement"}</Link>
                        <small>Run <code>{run.run_id.slice(0, 8)}</code></small>
                      </td>
                      <td>{meta.stage}</td>
                      <td><StatusBadge status={run.status} /></td>
                      <td>{new Date(run.created_at).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })}</td>
                      <td><Link className="row-chevron" href={`/runs/${run.run_id}`} aria-label={`Open ${run.raw_requirement_text}`}>›</Link></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <div className="run-cards">
            {filtered.map((run) => {
              const meta = runStatusMeta(run.status);
              return (
                <Link className="run-card" href={`/runs/${run.run_id}`} key={run.run_id}>
                  <span className="run-card-top"><StatusBadge status={run.status} /><code>{run.run_id.slice(0, 8)}</code></span>
                  <strong>{run.raw_requirement_text || "Untitled requirement"}</strong>
                  <span className="run-card-meta"><span>{meta.stage}</span><span>{new Date(run.created_at).toLocaleDateString()}</span></span>
                </Link>
              );
            })}
          </div>
        </>
      )}
    </section>
  );
}
