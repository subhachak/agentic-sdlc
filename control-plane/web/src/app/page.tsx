import Link from "next/link";
import { getDashboard } from "@/lib/api";
import type { DashboardData } from "@/lib/types";

export const dynamic = "force-dynamic";

/**
 * What needs attention, and nothing else.
 *
 * This page used to restate the engagement and platform settings as two
 * read-only cards — a third copy of values that already lived in two places
 * and disagreed. Overview answers one question now: is anything waiting for
 * me, and can this thing ship? Everything it names links to the page that
 * owns it rather than duplicating it.
 */

const WAITING: Record<
  DashboardData["recent"][number]["waiting_on"],
  { label: string; tone: string }
> = {
  awaiting_human: { label: "Needs approval", tone: "warn" },
  awaiting_machine: { label: "Waiting for CI", tone: "busy" },
  working: { label: "In progress", tone: "busy" },
  finished: { label: "Finished", tone: "ok" },
};

export default async function OverviewPage() {
  let data: DashboardData | null = null;
  let error: string | null = null;
  try {
    data = await getDashboard();
  } catch (err) {
    error = err instanceof Error ? err.message : String(err);
  }

  if (!data) {
    return (
      <main>
        <div className="page-head">
          <h1>Overview</h1>
        </div>
        <div className="notice crit">
          <h3>The control plane is not reachable</h3>
          <p>{error}</p>
        </div>
      </main>
    );
  }

  const { runs, coverage, graph, recent, dispatches, hydration } = data;
  const pending = dispatches.pending ?? 0;
  const tested = coverage.criteria ? Math.round((coverage.tested / coverage.criteria) * 100) : 0;

  return (
    <main>
      <div className="page-head">
        <h1>Overview</h1>
        <p>What the platform is running, what it is waiting on, and what it can prove.</p>
      </div>

      {!hydration.hydrated && (
        <div className="notice warn">
          <h3>Setup is incomplete</h3>
          <p>
            Runs will not produce trustworthy results until this is finished — a design
            phase refuses against an empty graph, and scoping from a stale one describes the
            wrong commit.
          </p>
          <ul>
            {hydration.steps
              .filter((step) => !step.ready)
              .map((step) => (
                <li key={step.id}>
                  <strong>{step.title}</strong> — {step.detail}
                </li>
              ))}
          </ul>
          <p style={{ marginTop: "var(--s3)" }}>
            <Link href="/setup">Finish setup →</Link>
          </p>
        </div>
      )}

      <div className="stats">
        <div className={`stat ${runs.awaiting_human ? "attention" : ""}`}>
          <span className="stat-label">Needs a person</span>
          <span className="stat-value">{runs.awaiting_human}</span>
          <span className="stat-note">
            {runs.awaiting_human ? "gate approval" : "nothing blocked"}
          </span>
        </div>
        <div className="stat">
          <span className="stat-label">Waiting for CI</span>
          <span className="stat-value">{runs.awaiting_machine}</span>
          <span className="stat-note">
            {pending ? `${pending} dispatch${pending === 1 ? "" : "es"} in flight` : "no jobs"}
          </span>
        </div>
        <div className={`stat ${coverage.untested ? "bad" : coverage.criteria ? "good" : ""}`}>
          <span className="stat-label">Untested criteria</span>
          <span className="stat-value">{coverage.untested}</span>
          <span className="stat-note">
            {coverage.criteria === 0 ? "graph not seeded" : "no passing test"}
          </span>
        </div>
        <div className="stat">
          <span className="stat-label">Runs</span>
          <span className="stat-value">{runs.total}</span>
          <span className="stat-note">all time</span>
        </div>
        <div className="stat">
          <span className="stat-label">Modules</span>
          <span className="stat-value">{graph.modules}</span>
          <span className="stat-note">{graph.dependencies} dependencies</span>
        </div>
      </div>

      <section className="panel">
        <div className="panel-head">
          <div>
            <h2>Release readiness</h2>
            <p>
              An acceptance criterion counts as covered only when a test that claims it was
              observed to run and pass.
            </p>
          </div>
          <div className="panel-head-end">
            <span className={`pill ${coverage.untested ? "warn" : coverage.criteria ? "ok" : "idle"}`}>
              {coverage.criteria === 0 ? "No criteria" : `${tested}% covered`}
            </span>
          </div>
        </div>
        <div className="panel-body">
          <div className="meter" role="img" aria-label={`${tested}% of criteria covered`}>
            <div
              className={`meter-fill ${tested === 100 ? "" : tested === 0 ? "none" : "partial"}`}
              style={{ width: `${tested}%` }}
            />
          </div>
          <p className="muted" style={{ marginTop: "var(--s2)", fontSize: "0.85rem" }}>
            {coverage.tested} of {coverage.criteria} criteria
          </p>
        </div>
        {coverage.gaps.length > 0 && (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Criterion with no passing test</th>
                  <th>Text</th>
                </tr>
              </thead>
              <tbody>
                {coverage.gaps.map((gap) => (
                  <tr key={gap.id}>
                    <td>
                      <code>{gap.id}</code>
                    </td>
                    <td className="muted">{gap.text || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="panel">
        <div className="panel-head">
          <div>
            <h2>Recent runs</h2>
          </div>
          <div className="panel-head-end">
            <Link href="/new">
              <button>Start a run</button>
            </Link>
          </div>
        </div>
        {recent.length === 0 ? (
          <div className="panel-body">
            <p className="muted" style={{ margin: 0 }}>
              No runs yet.
            </p>
          </div>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Requirement</th>
                  <th>State</th>
                  <th>Started</th>
                </tr>
              </thead>
              <tbody>
                {recent.map((run) => (
                  <tr key={run.run_id}>
                    <td>
                      <Link href={`/runs/${run.run_id}`}>
                        {run.requirement.slice(0, 70) || "(no text)"}
                      </Link>
                    </td>
                    <td>
                      <span className={`pill ${WAITING[run.waiting_on].tone}`}>
                        {WAITING[run.waiting_on].label}
                      </span>
                    </td>
                    <td className="muted">{new Date(run.created_at).toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </main>
  );
}
