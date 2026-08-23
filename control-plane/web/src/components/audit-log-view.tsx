import type { AuditEntry } from "@/lib/types";

export default function AuditLogView({ entries }: { entries: AuditEntry[] }) {
  return (
    <div className="card">
      <h3 style={{ marginTop: 0 }}>Audit trail</h3>
      <p className="muted" style={{ fontSize: "0.85rem", marginTop: "-0.5rem" }}>
        Every node execution and every gate decision, before and after — the governance record for
        this run.
      </p>
      {entries.length === 0 ? (
        <p className="muted">No entries yet.</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Node</th>
              <th>Phase</th>
              <th>Confirmed</th>
              <th>Decision</th>
              <th>Time</th>
            </tr>
          </thead>
          <tbody>
            {entries.map((e, i) => (
              <tr key={`${e.node_name}-${e.phase}-${i}`}>
                <td>{e.node_name}</td>
                <td>{e.phase}</td>
                <td>{e.confirmed ? "yes" : "no"}</td>
                <td>{e.human_decision ?? "—"}</td>
                <td className="muted">{new Date(e.timestamp).toLocaleTimeString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
