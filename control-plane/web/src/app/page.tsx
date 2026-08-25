import Link from "next/link";
import type { CSSProperties } from "react";
import { getDashboard } from "@/lib/api";
import StatusBadge, { runStatusMeta } from "@/components/status-badge";

export const dynamic = "force-dynamic";

function shortSha(value: string | null) {
  return value ? value.slice(0, 7) : "—";
}

export default async function OverviewPage() {
  let data;
  try {
    data = await getDashboard();
  } catch (error) {
    return (
      <main>
        <div className="page-head">
          <div className="page-head-copy">
            <span className="eyebrow">Delivery operations</span>
            <h1>Command center</h1>
            <p>Live control and assurance across the active client engagement.</p>
          </div>
        </div>
        <div className="notice crit" role="alert">
          <h3>The control plane is unavailable</h3>
          <p>{error instanceof Error ? error.message : String(error)}</p>
        </div>
      </main>
    );
  }

  const { runs, coverage, graph, recent, hydration, engagement } = data;
  const coveragePercent = coverage.criteria
    ? Math.round((coverage.tested / coverage.criteria) * 100)
    : 0;
  const failed = Object.entries(runs.by_status).reduce((total, [status, count]) => {
    const meta = runStatusMeta(status);
    return total + (meta.terminal && meta.tone === "crit" ? count : 0);
  }, 0);
  const inFlight = runs.working + runs.awaiting_machine;
  const failedRecent = recent.find((run) => runStatusMeta(run.status).tone === "crit");
  const attentionCount =
    runs.awaiting_human + failed + coverage.untested + (hydration.hydrated ? 0 : 1);

  return (
    <main>
      <div className="page-head">
        <div className="page-head-copy">
          <span className="eyebrow">Delivery operations</span>
          <h1>Command center</h1>
          <p>
            Priorities, delivery outcomes and release evidence for the active engagement.
          </p>
        </div>
        <div className="page-actions">
          <Link href="/runs" className="button-link secondary">
            View all runs
          </Link>
          <Link href="/new" className="button-link">
            <span aria-hidden>＋</span> Start a run
          </Link>
        </div>
      </div>

      <section className="context-banner" aria-label="Active delivery context">
        <div className="context-block primary">
          <span className="context-symbol" aria-hidden>RE</span>
          <span className="truncate">
            <span className="context-label">Indexed repository</span>
            <span className="context-value">{engagement.indexed_repo || "Not connected"}</span>
          </span>
        </div>
        <div className="context-block">
          <span className="context-label">Branch</span>
          <span className="context-value"><code>{engagement.indexed_ref || "—"}</code></span>
        </div>
        <div className="context-block">
          <span className="context-label">Environment</span>
          <span className="context-value">{engagement.environment || "—"}</span>
        </div>
        <div className="context-block">
          <span className="context-label">Indexed revision</span>
          <span className="context-value"><code>{shortSha(engagement.commit)}</code></span>
        </div>
      </section>

      {!hydration.hydrated && (
        <div className="notice warn">
          <h3>Complete the workspace before starting delivery</h3>
          <p>
            {hydration.steps.filter((step) => !step.ready).map((step) => step.title).join(", ")}.
            {" "}<Link href="/setup">Resolve setup requirements</Link>
          </p>
        </div>
      )}

      <section className="metric-grid" aria-label="Delivery metrics">
        <article className={`metric-card ${runs.awaiting_human ? "attention" : ""}`}>
          <span className="metric-label">Approval required <span className="metric-marker" /></span>
          <strong className="metric-value">{runs.awaiting_human}</strong>
          <span className="metric-note">Human decisions waiting now</span>
        </article>
        <article className="metric-card">
          <span className="metric-label">Automation active <span className="metric-marker" /></span>
          <strong className="metric-value">{inFlight}</strong>
          <span className="metric-note">Agents and CI currently working</span>
        </article>
        <article className={`metric-card ${failed ? "critical" : ""}`}>
          <span className="metric-label">Failed or stopped <span className="metric-marker" /></span>
          <strong className="metric-value">{failed}</strong>
          <span className="metric-note">Terminal runs requiring review</span>
        </article>
        <article className={`metric-card ${coverage.untested ? "attention" : ""}`}>
          <span className="metric-label">Criteria verified <span className="metric-marker" /></span>
          <strong className="metric-value">{coverage.criteria ? `${coveragePercent}%` : "—"}</strong>
          <span className="metric-note">
            {coverage.criteria ? `${coverage.tested} of ${coverage.criteria}` : "No criteria captured yet"}
          </span>
        </article>
      </section>

      <div className="dashboard-grid">
        <div className="dashboard-main">
          <section className="panel elevated">
            <div className="panel-head">
              <div>
                <h2>Attention queue</h2>
                <p>Exceptions and human decisions ordered ahead of passive activity.</p>
              </div>
              <div className="panel-head-end">
                <span className={`pill ${attentionCount ? "warn" : "ok"}`}>
                  {attentionCount ? `${attentionCount} item${attentionCount === 1 ? "" : "s"}` : "Clear"}
                </span>
              </div>
            </div>

            {attentionCount === 0 ? (
              <div className="attention-empty">
                <span className="attention-symbol" aria-hidden>✓</span>
                <h3>No intervention required</h3>
                <p>Active automation can continue without an administrative or engineering decision.</p>
              </div>
            ) : (
              <div className="panel-body flush">
                {!hydration.hydrated && (
                  <div className="row">
                    <div className="row-main">
                      <div className="row-label">Workspace setup is incomplete</div>
                      <div className="row-help">The graph, grounding index and QA handoff must describe the same revision.</div>
                    </div>
                    <div className="row-end"><Link href="/setup" className="button-link secondary">Review setup</Link></div>
                  </div>
                )}
                {runs.awaiting_human > 0 && (
                  <div className="row">
                    <div className="row-main">
                      <div className="row-label">{runs.awaiting_human} gate decision{runs.awaiting_human === 1 ? "" : "s"} waiting</div>
                      <div className="row-help">A person must review the evidence before these runs can move forward.</div>
                    </div>
                    <div className="row-end"><Link href="/runs" className="button-link secondary">Open queue</Link></div>
                  </div>
                )}
                {failed > 0 && (
                  <div className="row">
                    <div className="row-main">
                      <div className="row-label">{failed} delivery run{failed === 1 ? "" : "s"} did not complete successfully</div>
                      <div className="row-help">Review the failed phase and its captured evidence before retrying.</div>
                    </div>
                    <div className="row-end">
                      <Link href={failedRecent ? `/runs/${failedRecent.run_id}` : "/runs"} className="button-link secondary">Inspect failure</Link>
                    </div>
                  </div>
                )}
                {coverage.untested > 0 && (
                  <div className="row">
                    <div className="row-main">
                      <div className="row-label">{coverage.untested} acceptance {coverage.untested === 1 ? "criterion" : "criteria"} without passing evidence</div>
                      <div className="row-help">Release readiness remains incomplete until observed tests pass.</div>
                    </div>
                    <div className="row-end"><Link href="/quality" className="button-link secondary">Review coverage</Link></div>
                  </div>
                )}
              </div>
            )}
          </section>

          <section className="panel">
            <div className="panel-head">
              <div>
                <h2>Recent delivery runs</h2>
                <p>The latest requirements processed in this engagement.</p>
              </div>
              <div className="panel-head-end"><Link href="/runs">View all</Link></div>
            </div>
            {recent.length === 0 ? (
              <div className="empty-state">
                <span className="empty-state-mark">RUN</span>
                <h3>No delivery runs yet</h3>
                <p>Start with one plain-language outcome; the platform derives the governed workflow.</p>
                <Link href="/new" className="button-link">Start the first run</Link>
              </div>
            ) : (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr><th>Requirement</th><th>Stage</th><th>Outcome</th><th>Started</th><th aria-label="Open" /></tr>
                  </thead>
                  <tbody>
                    {recent.map((run) => {
                      const meta = runStatusMeta(run.status);
                      return (
                        <tr key={run.run_id}>
                          <td className="table-primary">
                            <Link className="table-link" href={`/runs/${run.run_id}`}>{run.requirement || "Untitled requirement"}</Link>
                            <small><code>{run.run_id.slice(0, 8)}</code></small>
                          </td>
                          <td>{meta.stage}</td>
                          <td><StatusBadge status={run.status} /></td>
                          <td>{new Date(run.created_at).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" })}</td>
                          <td><Link className="row-chevron" href={`/runs/${run.run_id}`} aria-label={`Open ${run.requirement}`}>›</Link></td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </div>

        <aside className="dashboard-side">
          <section className="panel">
            <div className="panel-head"><div><h2>Release evidence</h2><p>Observed passing tests, not declared coverage.</p></div></div>
            <div className="panel-body readiness-layout">
              <div className="readiness-ring" style={{ "--progress": `${coveragePercent * 3.6}deg` } as CSSProperties}>
                <div className="readiness-score"><strong>{coverage.criteria ? `${coveragePercent}%` : "—"}</strong><span>verified</span></div>
              </div>
              <div className="readiness-copy">
                <h3>{coverage.criteria === 0 ? "No criteria captured" : coverage.untested ? "Evidence is incomplete" : "Evidence is complete"}</h3>
                <p>{coverage.criteria === 0 ? "Coverage populates as governed runs assert acceptance criteria." : `${coverage.untested} criteria still need passing evidence.`}</p>
                <div className="mini-stats">
                  <span className="mini-stat"><strong>{coverage.tested}</strong><span>Verified</span></span>
                  <span className="mini-stat"><strong>{coverage.untested}</strong><span>Open</span></span>
                </div>
              </div>
            </div>
          </section>

          <section className="panel">
            <div className="panel-head"><div><h2>Platform readiness</h2><p>Evidence inputs used by design and QA.</p></div></div>
            <div className="panel-body readiness-list">
              {hydration.steps.map((step) => (
                <div className="readiness-item" key={step.id}>
                  <span className={`readiness-check ${step.ready ? "" : "pending"}`} aria-hidden>{step.ready ? "✓" : "!"}</span>
                  <span><strong>{step.title}</strong><span>{step.detail}</span></span>
                </div>
              ))}
              <div className="readiness-item">
                <span className="readiness-check" aria-hidden>✓</span>
                <span><strong>Architecture graph</strong><span>{graph.modules} modules · {graph.dependencies} dependencies</span></span>
              </div>
            </div>
          </section>
        </aside>
      </div>
    </main>
  );
}
