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


/**
 * One configured fact. Absent is stated rather than left blank: an empty cell
 * reads as "nothing to show here", and the useful message is that a field
 * nothing has filled in is why the next run will not work.
 */
function Fact({
  label,
  value,
  suffix,
}: {
  label: string;
  value: string | null | undefined;
  suffix?: string | null;
}) {
  return (
    <>
      <dt>{label}</dt>
      <dd>
        {value ? (
          <>
            <code>{value}</code>
            {suffix && <span className="muted"> · {suffix}</span>}
          </>
        ) : (
          <span className="muted">not set</span>
        )}
      </dd>
    </>
  );
}

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

  const { runs, coverage, graph, recent, dispatches, engagement, platform, credentials, hydration } = data;
  const pending = dispatches.pending ?? 0;

  return (
    <main className="wide">
      <h1>Dashboard</h1>
      <p className="muted" style={{ marginTop: "-0.5rem" }}>
        What the platform is running, what it is waiting on, and what it can prove.
      </p>

      {!hydration.hydrated && (
        <div className="card notice">
          <strong>Setup is incomplete.</strong> Runs will not produce trustworthy results
          until the graph is populated — a design phase refuses against an empty graph, and
          scoping derived from a stale one describes the wrong commit.
          <ul style={{ margin: "0.5rem 0 0.5rem 1.1rem", padding: 0 }}>
            {hydration.steps
              .filter((step) => !step.ready)
              .map((step) => (
                <li key={step.id} style={{ fontSize: "0.85rem" }}>
                  <strong>{step.title}</strong> — {step.detail}
                </li>
              ))}
          </ul>
          <Link href="/operations">Go to Operations</Link>
        </div>
      )}

      <div className="card">
        <h2 style={{ marginTop: 0, fontSize: "1rem" }}>
          This engagement{" "}
          <span className="muted" style={{ fontWeight: 400, fontSize: "0.8rem" }}>
            — <Link href="/config">configure</Link>
          </span>
        </h2>
        <dl className="facts">
          <Fact label="Codebase indexed" value={engagement.indexed_repo} suffix={engagement.indexed_ref} />
          <Fact label="At commit" value={engagement.commit?.slice(0, 7) ?? null}
                suffix={engagement.indexed_at ? new Date(engagement.indexed_at).toLocaleString() : null} />
          <Fact label="Changes proposed against" value={engagement.target_repo} suffix={engagement.target_ref} />
          <Fact label="CI repository" value={engagement.ci_repo} />
          <Fact label="Deploys to" value={engagement.environment} />
          <Fact label="Tested subtree" value={engagement.export_scope} />
        </dl>
      </div>

      <div className="card">
        <h2 style={{ marginTop: 0, fontSize: "1rem" }}>
          Platform{" "}
          <span className="muted" style={{ fontWeight: 400, fontSize: "0.8rem" }}>
            — <Link href="/config">configure</Link>
          </span>
        </h2>
        <dl className="facts">
          <Fact label="Model" value={platform.model_provider === "mock" ? "mock (no model)" : platform.model} />
          <Fact label="Runs QA on" value={platform.execution_target} />
          <Fact label="Indexes from" value={platform.index_source} />
          <Fact label="Proposes changes via" value={platform.change_target} />
          <Fact label="Gates" value={platform.gates} />
          <Fact
            label="Credentials"
            value={
              Object.entries(credentials)
                .filter(([, present]) => present)
                .map(([name]) => name.replace(/_/g, " "))
                .join(", ") || null
            }
          />
        </dl>
      </div>

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
        <StatTile label="Modules" value={graph.modules} note={`${graph.dependencies} dependencies`} />
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

    </main>
  );
}
