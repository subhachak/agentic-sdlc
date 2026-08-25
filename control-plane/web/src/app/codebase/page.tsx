"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import {
  getDashboard,
  getGraphExport,
  hydrationStatus,
  listModules,
  type GraphExportData,
  type HydrationStatus,
} from "@/lib/api";
import type { DashboardData, ModuleEntry } from "@/lib/types";

type IntelligenceData = {
  modules: ModuleEntry[];
  status: HydrationStatus;
  dashboard: DashboardData;
  graphExport: GraphExportData | null;
};

export default function CodebasePage() {
  const [data, setData] = useState<IntelligenceData | null>(null);
  const [query, setQuery] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void (async () => {
      try {
        const [moduleResult, status, dashboard] = await Promise.all([
          listModules(),
          hydrationStatus(),
          getDashboard(),
        ]);
        let graphExport: GraphExportData | null = null;
        try {
          graphExport = await getGraphExport(dashboard.engagement.export_scope || "");
        } catch {
          // The module inventory remains useful before the execution export exists.
        }
        setData({ modules: moduleResult.modules, status, dashboard, graphExport });
      } catch (reason) {
        setError(reason instanceof Error ? reason.message : String(reason));
      }
    })();
  }, []);

  const filtered = useMemo(() => {
    if (!data) return [];
    const normalized = query.trim().toLowerCase();
    if (!normalized) return data.modules;
    return data.modules.filter((module) =>
      `${module.id} ${module.depends_on.map((dependency) => dependency.target).join(" ")}`
        .toLowerCase()
        .includes(normalized)
    );
  }, [data, query]);

  if (error) {
    return (
      <main>
        <div className="page-head"><div className="page-head-copy"><span className="eyebrow">Architecture evidence</span><h1>Code intelligence</h1></div></div>
        <div className="notice crit" role="alert"><h3>Code intelligence is unavailable</h3><p>{error}</p></div>
      </main>
    );
  }

  const modules = data?.modules ?? [];
  const totalFiles = modules.reduce((total, module) => total + module.files, 0);
  const dependencies = modules.reduce((total, module) => total + module.depends_on.length, 0);
  const maxFiles = Math.max(...modules.map((module) => module.files), 1);
  const routes = Object.entries(data?.graphExport?.routes ?? {});
  const provenance = data?.status.provenance;
  const captureRate = provenance?.internal_capture_rate;

  return (
    <main>
      <div className="page-head">
        <div className="page-head-copy">
          <span className="eyebrow">Architecture evidence</span>
          <h1>Code intelligence</h1>
          <p>Repository-derived module, dependency and route evidence used to contain design and inform QA scope.</p>
        </div>
        <div className="page-actions"><Link href="/setup" className="button-link secondary">Manage repository index</Link></div>
      </div>

      {!data ? (
        <section className="panel"><div className="panel-body"><p className="muted">Loading the architecture index…</p></div></section>
      ) : modules.length === 0 ? (
        <section className="panel empty-state">
          <span className="empty-state-mark">IDX</span>
          <h3>No repository has been indexed</h3>
          <p>Connect a repository once; branch, graph, retrieval and QA export are then maintained together.</p>
          <Link href="/setup" className="button-link">Connect repository</Link>
        </section>
      ) : (
        <>
          <section className="intelligence-hero">
            <div className="intelligence-context">
              <span className="eyebrow">Indexed source of truth</span>
              <h2>{provenance?.repo || data.dashboard.engagement.indexed_repo || "Repository"}</h2>
              <p>The index is pinned to a concrete revision and parsed without executing fetched source.</p>
              <div className="provenance-line">
                <span className={`pill ${provenance?.pinned ? "ok" : "warn"}`}>{provenance?.pinned ? "Revision pinned" : "Unpinned"}</span>
                <span className="pill idle">branch {data.dashboard.engagement.indexed_ref || "—"}</span>
                <span className="pill idle">scope {data.dashboard.engagement.export_scope || "repository"}</span>
                <span className="pill idle"><code>{provenance?.commit_sha?.slice(0, 7) || "no sha"}</code></span>
              </div>
            </div>
            <div className="quality-card">
              <span className="context-label">Internal dependency capture</span>
              <div className="quality-score"><strong>{captureRate === null || captureRate === undefined ? "—" : `${(captureRate * 100).toFixed(1)}%`}</strong><span>resolved imports</span></div>
              <p>This is graph construction quality—not a claim that business blast radius is complete.</p>
              <div className="meter" role="img" aria-label={`${captureRate ? (captureRate * 100).toFixed(1) : 0}% of internal imports resolved`}>
                <div className={`meter-fill ${(captureRate ?? 0) < .8 ? "partial" : ""}`} style={{ width: `${Math.min((captureRate ?? 0) * 100, 100)}%` }} />
              </div>
            </div>
          </section>

          <section className="metric-grid" aria-label="Architecture index metrics">
            <article className="metric-card"><span className="metric-label">Modules <span className="metric-marker" /></span><strong className="metric-value">{modules.length}</strong><span className="metric-note">Logical code areas</span></article>
            <article className="metric-card"><span className="metric-label">Source files <span className="metric-marker" /></span><strong className="metric-value">{totalFiles}</strong><span className="metric-note">Assigned to modules</span></article>
            <article className="metric-card"><span className="metric-label">Dependencies <span className="metric-marker" /></span><strong className="metric-value">{dependencies}</strong><span className="metric-note">Module-to-module edges</span></article>
            <article className="metric-card"><span className="metric-label">Application routes <span className="metric-marker" /></span><strong className="metric-value">{routes.length}</strong><span className="metric-note">In the QA execution scope</span></article>
          </section>

          <div className="architecture-layout">
            <section className="panel elevated">
              <div className="panel-head"><div><h2>Module architecture</h2><p>Structural dependencies derived from imports and HTTP contracts.</p></div></div>
              <div className="toolbar">
                <label className="search-control">
                  <span className="sr-only">Search modules</span>
                  <input type="search" value={query} placeholder="Search module or dependency" onChange={(event) => setQuery(event.target.value)} />
                </label>
                <span className="result-count">{filtered.length} of {modules.length} modules</span>
              </div>
              <div className="table-wrap">
                <table>
                  <thead><tr><th>Module</th><th className="num">Files</th><th>Direct dependencies</th></tr></thead>
                  <tbody>
                    {filtered.map((module) => (
                      <tr key={module.id}>
                        <td className="table-primary">
                          <div className="module-name"><span className="module-glyph">M</span><span><strong><code>{module.id}</code></strong><span className="module-bar"><span style={{ width: `${Math.max((module.files / maxFiles) * 100, 4)}%` }} /></span></span></div>
                        </td>
                        <td className="num">{module.files}</td>
                        <td>
                          {module.depends_on.length === 0 ? <span className="muted">No outbound module edge</span> : (
                            <div className="dependency-list">
                              {module.depends_on.slice(0, 4).map((dependency) => <span className="dependency-chip" key={dependency.target}>{dependency.target.split("/").pop()} ×{dependency.weight}</span>)}
                              {module.depends_on.length > 4 && <span className="dependency-chip">+{module.depends_on.length - 4} more</span>}
                            </div>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>

            <aside>
              <section className="panel">
                <div className="panel-head"><div><h2>Execution surface</h2><p>Routes mapped to files in the exported QA scope.</p></div></div>
                <div className="panel-body route-list">
                  {routes.length === 0 ? <p className="muted">No route map in the current export.</p> : routes.slice(0, 10).map(([route, files]) => (
                    <div className="route-item" key={route}><code>{route}</code><span>{files.length} file{files.length === 1 ? "" : "s"}</span></div>
                  ))}
                </div>
              </section>
              <section className="panel">
                <div className="panel-head"><div><h2>Graph provenance</h2><p>Technical evidence behind structural calculations.</p></div></div>
                <div className="panel-body evidence-list">
                  <div className="evidence-item"><span>Indexer</span><strong>{provenance?.indexer_version || "—"}</strong></div>
                  <div className="evidence-item"><span>Indexed</span><strong>{provenance?.indexed_at ? new Date(provenance.indexed_at).toLocaleString() : "—"}</strong></div>
                  <div className="evidence-item"><span>Deployable units</span><strong>{data.graphExport?.provenance.units?.join(", ") || "Not reported"}</strong></div>
                  <div className="evidence-item"><span>Known unresolved imports</span><strong>{data.graphExport?.provenance.most_missed?.slice(0, 3).map(([name, count]) => `${name} (${count})`).join(", ") || "None reported"}</strong></div>
                </div>
              </section>
            </aside>
          </div>
        </>
      )}
    </main>
  );
}
