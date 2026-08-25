import type { AuditEntry } from "@/lib/types";

function label(value: string) {
  return value.replaceAll("_", " ").replace(/\b\w/g, (character) => character.toUpperCase());
}

function outcome(entry: AuditEntry) {
  if (entry.human_decision) return `Decision · ${entry.human_decision}`;
  const output = entry.output_summary ?? {};
  if (typeof output.status === "string") return label(output.status);
  if (entry.confidence_score !== null) return `Completed · confidence ${Math.round(entry.confidence_score * 100)}%`;
  return entry.phase === "after" ? "Completed" : "Started";
}

export default function AuditLogView({ entries }: { entries: AuditEntry[] }) {
  const after = entries.filter((entry) => entry.phase === "after");
  const completedNodes = new Set(after.map((entry) => entry.node_name));
  const activeBefore = entries.filter((entry) => entry.phase === "before" && !completedNodes.has(entry.node_name)).slice(-1);
  const events = [...after, ...activeBefore].sort((a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime());

  return (
    <section className="panel">
      <div className="panel-head"><div><h2>Governance activity</h2><p>One readable event per completed control; full before-and-after payloads remain available below.</p></div><span className="pill idle">{events.length} events</span></div>
      <div className="panel-body">
        {events.length === 0 ? <p className="muted">The first control has not reported yet.</p> : (
          <div className="audit-timeline">
            {events.map((entry, index) => (
              <div className={`audit-entry ${entry.human_decision ?? ""}`} key={`${entry.node_name}-${entry.phase}-${entry.timestamp}-${index}`}>
                <span className="audit-dot" aria-hidden>{entry.human_decision === "approved" ? "✓" : entry.human_decision === "rejected" ? "!" : entry.phase === "after" ? "✓" : "•"}</span>
                <span className="audit-copy"><strong>{label(entry.node_name)}</strong><span>{outcome(entry)}</span></span>
                <time className="audit-time" dateTime={entry.timestamp}>{new Date(entry.timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}</time>
              </div>
            ))}
          </div>
        )}
      </div>
      <details className="disclosure">
        <summary>Full technical audit · {entries.length} before/after records</summary>
        <div className="panel-body"><pre>{JSON.stringify(entries, null, 2)}</pre></div>
      </details>
    </section>
  );
}
