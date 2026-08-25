import Link from "next/link";
import type { CSSProperties } from "react";
import { getDashboard } from "@/lib/api";
import StatusBadge, { runStatusMeta } from "@/components/status-badge";

export const dynamic = "force-dynamic";

export default async function QualityPage() {
  let data;
  try {
    data = await getDashboard();
  } catch (error) {
    return <main><div className="page-head"><div className="page-head-copy"><span className="eyebrow">Release assurance</span><h1>Quality evidence</h1></div></div><div className="notice crit" role="alert"><h3>Quality evidence is unavailable</h3><p>{error instanceof Error ? error.message : String(error)}</p></div></main>;
  }

  const coverage = data.coverage;
  const verified = coverage.criteria ? Math.round((coverage.tested / coverage.criteria) * 100) : 0;
  const qaFailures = Object.entries(data.runs.by_status).reduce((total, [status, count]) => total + (runStatusMeta(status).stage === "QA" && runStatusMeta(status).tone === "crit" ? count : 0), 0);
  const qaRuns = data.recent.filter((run) => runStatusMeta(run.status).stage === "QA" || run.status === "completed");

  return (
    <main>
      <div className="page-head">
        <div className="page-head-copy"><span className="eyebrow">Release assurance</span><h1>Quality evidence</h1><p>Observed test outcomes, acceptance-criterion gaps and the controls that make release evidence trustworthy.</p></div>
        <div className="page-actions"><Link href="/runs" className="button-link secondary">Review delivery runs</Link><Link href="/new" className="button-link">Start a run</Link></div>
      </div>

      <section className="context-banner" aria-label="Quality evidence context">
        <div className="context-block primary"><span className="context-symbol" aria-hidden>QA</span><span className="truncate"><span className="context-label">Assured repository</span><span className="context-value">{data.engagement.indexed_repo || "Not connected"}</span></span></div>
        <div className="context-block"><span className="context-label">Execution scope</span><span className="context-value"><code>{data.engagement.export_scope || "—"}</code></span></div>
        <div className="context-block"><span className="context-label">Target environment</span><span className="context-value">{data.engagement.environment || "—"}</span></div>
        <div className="context-block"><span className="context-label">Release policy</span><span className="context-value">{data.platform.gates === "human" ? "Human gated" : "Automated"}</span></div>
      </section>

      <section className="metric-grid" aria-label="Quality metrics">
        <article className={`metric-card ${coverage.untested ? "attention" : ""}`}><span className="metric-label">Criteria verified <span className="metric-marker" /></span><strong className="metric-value">{coverage.criteria ? `${verified}%` : "—"}</strong><span className="metric-note">Observed and passing</span></article>
        <article className={`metric-card ${coverage.criteria && coverage.untested ? "critical" : ""}`}><span className="metric-label">Evidence gaps <span className="metric-marker" /></span><strong className="metric-value">{coverage.criteria ? coverage.untested : "—"}</strong><span className="metric-note">{coverage.criteria ? "Criteria without a passing test" : "No criteria captured yet"}</span></article>
        <article className={`metric-card ${qaFailures ? "critical" : ""}`}><span className="metric-label">QA failures <span className="metric-marker" /></span><strong className="metric-value">{qaFailures}</strong><span className="metric-note">Failed or timed-out QA phases</span></article>
        <article className="metric-card"><span className="metric-label">Governed runs <span className="metric-marker" /></span><strong className="metric-value">{data.runs.total}</strong><span className="metric-note">Evidence-producing workflows</span></article>
      </section>

      <div className="dashboard-grid">
        <div className="dashboard-main">
          <section className="panel elevated">
            <div className="panel-head"><div><h2>Acceptance-criterion coverage</h2><p>A criterion is verified only when a linked test was observed to execute and pass.</p></div><span className={`pill ${coverage.criteria === 0 ? "idle" : coverage.untested ? "warn" : "ok"}`}>{coverage.criteria === 0 ? "No criteria" : coverage.untested ? "Incomplete" : "Complete"}</span></div>
            <div className="panel-body readiness-layout">
              <div className="readiness-ring" style={{ "--progress": `${verified * 3.6}deg` } as CSSProperties}><div className="readiness-score"><strong>{coverage.criteria ? `${verified}%` : "—"}</strong><span>verified</span></div></div>
              <div className="readiness-copy"><h3>{coverage.criteria === 0 ? "Coverage begins with governed criteria" : `${coverage.tested} of ${coverage.criteria} criteria have passing evidence`}</h3><p>{coverage.criteria === 0 ? "Run synthesis and QA will populate traceable acceptance evidence." : "Declared test mappings alone do not count toward this number."}</p><div className="meter"><div className={`meter-fill ${verified < 100 ? "partial" : ""}`} style={{ width: `${verified}%` }} /></div></div>
            </div>
            {coverage.gaps.length > 0 && <div className="table-wrap"><table><thead><tr><th>Open criterion</th><th>Requirement text</th></tr></thead><tbody>{coverage.gaps.map((gap) => <tr key={gap.id}><td><code>{gap.id}</code></td><td>{gap.text || "No criterion text reported"}</td></tr>)}</tbody></table></div>}
          </section>

          <section className="panel">
            <div className="panel-head"><div><h2>Recent QA outcomes</h2><p>Runs that reached assurance or completed release.</p></div><Link href="/runs">All runs</Link></div>
            {qaRuns.length === 0 ? <div className="empty-state"><span className="empty-state-mark">QA</span><h3>No QA outcome has been recorded</h3><p>The execution plane will report observed results here after a change reaches QA.</p></div> : <div className="table-wrap"><table><thead><tr><th>Requirement</th><th>Outcome</th><th>Started</th></tr></thead><tbody>{qaRuns.map((run) => <tr key={run.run_id}><td className="table-primary"><Link className="table-link" href={`/runs/${run.run_id}`}>{run.requirement}</Link><small><code>{run.run_id.slice(0, 8)}</code></small></td><td><StatusBadge status={run.status} /></td><td>{new Date(run.created_at).toLocaleDateString()}</td></tr>)}</tbody></table></div>}
          </section>
        </div>

        <aside className="dashboard-side">
          <section className="panel">
            <div className="panel-head"><div><h2>Assurance control chain</h2><p>All three evidence foundations must be ready.</p></div></div>
            <div className="panel-body readiness-list">
              {data.hydration.steps.map((step) => <div className="readiness-item" key={step.id}><span className={`readiness-check ${step.ready ? "" : "pending"}`}>{step.ready ? "✓" : "!"}</span><span><strong>{step.title}</strong><span>{step.detail}</span></span></div>)}
              <div className="readiness-item"><span className="readiness-check">✓</span><span><strong>Deterministic gate</strong><span>Models do not decide QA pass or release approval.</span></span></div>
            </div>
          </section>
          <section className="panel">
            <div className="panel-head"><div><h2>Evidence standard</h2><p>What the console treats as release proof.</p></div></div>
            <div className="panel-body evidence-list"><div className="evidence-item"><span>Selection</span><strong>Change scope plus mandatory regressions</strong></div><div className="evidence-item"><span>Execution</span><strong>Observed script and route coverage</strong></div><div className="evidence-item"><span>Decision</span><strong>Deterministic policy outcome</strong></div><div className="evidence-item"><span>Record</span><strong>Revision-pinned audit evidence</strong></div></div>
          </section>
        </aside>
      </div>
    </main>
  );
}
