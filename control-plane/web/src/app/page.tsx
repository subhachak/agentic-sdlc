import Link from "next/link";
import CoverageMeter from "@/components/coverage-meter";
import StatTile from "@/components/stat-tile";
import { getDashboard } from "@/lib/api";
import type { DashboardData } from "@/lib/types";

export const dynamic = "force-dynamic";

const WAITING_LABEL: Record<DashboardData["recent"][number]["waiting_on"], string> = {
  awaiting_human: "waiting for a person",
  awaiting_machine: "waiting for CI",
  working: "in progress",
  finished: "finished",
};

const WAITING_TONE: Record<string, string> = {
  awaiting_human: "warning",
  awaiting_machine: "working",
  working: "working",
  finished: "good",
};

export default async function DashboardPage() {
  let data: DashboardData | null = null;
  let error: string | null = null;
  try {
    data = await getDashboard();
  } catch (err) {
    error = err instanceof Error ? err.message : String(err);
  }

  if (!data) {
    return (
      <main className="wide">
        <h1>Dashboard</h1>
        <div className="card">
          <p style={{ margin: 0 }}>The control plane is not reachable.</p>
          <p className="muted" style={{ marginBottom: 0 }}>{error}</p>
        </div>
      </main>
    );
  }

  const { runs, coverage, graph, recent, active, dispatches } = data;
  const pending = dispatches.pending ?? 0;

  return (
    <main className="wide">
      <h1>Dashboard</h1>
      <p className="muted" style={{ marginTop: "-0.5rem" }}>
        What the platform is running, what it is waiting on, and what it can prove.
      </p>

      <div className="tiles">
        <StatTile label="Runs" value={runs.total} large />
        <StatTile
          label="Waiting for a person"
          value={runs.awaiting_human}
          note={runs.awaiting_human ? "gate approval needed" : "nothing blocked"}
          tone={runs.awaiting_human ? "warning" : "neutral"}
        />
        <StatTile
          label="Waiting for CI"
          value={runs.awaiting_machine}
          note={pending ? `${pending} dispatch${pending === 1 ? "" : "es"} in flight` : "no jobs running"}
          tone={runs.awaiting_machine ? "working" : "neutral"}
        />
        <StatTile
          label="Untested criteria"
          value={coverage.untested}
          note={coverage.criteria === 0 ? "graph not seeded" : "no passing test"}
          tone={coverage.untested ? "critical" : "good"}
        />
        <StatTile label="Components" value={graph.components} note={`${graph.dependencies} dependencies`} />
      </div>

      <div className="card">
        <h2 style={{ marginTop: 0, fontSize: "1rem" }}>Release readiness</h2>
        <CoverageMeter tested={coverage.tested} total={coverage.criteria} />
        {coverage.gaps.length > 0 && (
          <table style={{ marginTop: "0.9rem" }}>
            <thead>
              <tr>
                <th>Criterion with no passing test</th>
                <th>Text</th>
              </tr>
            </thead>
            <tbody>
              {coverage.gaps.map((gap) => (
                <tr key={gap.id}>
                  <td><code>{gap.id}</code></td>
                  <td className="muted">{gap.text || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="card">
        <h2 style={{ marginTop: 0, fontSize: "1rem" }}>Recent runs</h2>
        {recent.length === 0 ? (
          <p className="muted" style={{ marginBottom: 0 }}>
            No runs yet. <Link href="/new">Start one →</Link>
          </p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Requirement</th>
                <th>Status</th>
                <th>Started</th>
              </tr>
            </thead>
            <tbody>
              {recent.map((run) => (
                <tr key={run.run_id}>
                  <td>
                    <Link href={`/runs/${run.run_id}`}>
                      {run.requirement.slice(0, 60) || "(no text)"}
                    </Link>
                  </td>
                  <td>
                    <span className="status">
                      <span className={`status-dot ${WAITING_TONE[run.waiting_on]}`} aria-hidden="true" />
                      {WAITING_LABEL[run.waiting_on]}
                    </span>
                  </td>
                  <td className="muted">{new Date(run.created_at).toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="card">
        <h2 style={{ marginTop: 0, fontSize: "1rem" }}>Active configuration</h2>
        <table>
          <tbody>
            <tr><td>Model provider</td><td><code>{active.model_provider}</code></td></tr>
            <tr><td>Execution target</td><td><code>{active.execution_target}</code></td></tr>
            <tr><td>Index source</td><td><code>{active.index_source}</code></td></tr>
            <tr><td>Indexed repository</td><td><code>{active.indexed_repo || "none"}</code></td></tr>
            <tr><td>Gates</td><td><code>{active.gates}</code></td></tr>
          </tbody>
        </table>
        <p className="muted" style={{ marginBottom: 0, marginTop: "0.75rem" }}>
          <Link href="/config">Change configuration →</Link>
        </p>
      </div>
    </main>
  );
}
