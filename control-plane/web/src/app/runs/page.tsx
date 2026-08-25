import Link from "next/link";
import { listRuns } from "@/lib/api";

export const dynamic = "force-dynamic";

const TONE: Record<string, string> = {
  completed: "ok",
  failed: "crit",
  rejected: "crit",
  awaiting_approval: "warn",
  running: "busy",
};

export default async function RunsListPage() {
  const runs = await listRuns();

  return (
    <main>
      <div className="page-head">
        <h1>Runs</h1>
        <p>Every delivery this platform has attempted, and how far each one got.</p>
      </div>

      <section className="panel">
        <div className="panel-head">
          <div>
            <h2>All runs</h2>
            <p>{runs.length === 0 ? "Nothing yet." : `${runs.length} total`}</p>
          </div>
          <div className="panel-head-end">
            <Link href="/new">
              <button>Start a run</button>
            </Link>
          </div>
        </div>
        {runs.length === 0 ? (
          <div className="panel-body">
            <p className="muted" style={{ margin: 0 }}>
              A run begins with a requirement in plain English.
            </p>
          </div>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Requirement</th>
                  <th>Status</th>
                  <th>Created</th>
                </tr>
              </thead>
              <tbody>
                {runs.map((r) => (
                  <tr key={r.run_id}>
                    <td>
                      <Link href={`/runs/${r.run_id}`}>
                        {r.raw_requirement_text.slice(0, 80)}
                      </Link>
                    </td>
                    <td>
                      <span className={`pill ${TONE[r.status] ?? "idle"}`}>{r.status}</span>
                    </td>
                    <td className="muted">{new Date(r.created_at).toLocaleString()}</td>
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
