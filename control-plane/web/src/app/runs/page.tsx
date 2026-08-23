import Link from "next/link";
import { listRuns } from "@/lib/api";

export default async function RunsListPage() {
  const runs = await listRuns();

  return (
    <main className="wide">
      <h1>Runs</h1>
      <p>
        <Link href="/new">Start a new run →</Link>
      </p>
      {runs.length === 0 ? (
        <p className="muted">No runs yet.</p>
      ) : (
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
                  <Link href={`/runs/${r.run_id}`}>{r.raw_requirement_text.slice(0, 80)}</Link>
                </td>
                <td>{r.status}</td>
                <td className="muted">{new Date(r.created_at).toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </main>
  );
}
