function colorFor(status: string): string {
  if (status === "completed") return "var(--success)";
  if (status.startsWith("rejected") || status.endsWith("_failed")) return "var(--danger)";
  if (status.startsWith("awaiting_gate")) return "var(--warning)";
  return "var(--accent)";
}

export default function StatusBadge({ status }: { status: string }) {
  return <span style={{ color: colorFor(status), fontWeight: 600 }}>{status.replaceAll("_", " ")}</span>;
}
