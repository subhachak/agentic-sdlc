"use client";

import { useState } from "react";
import { checkImplementationAgent } from "@/lib/api";

/**
 * Verify the configured implementation agent can actually be reached.
 *
 * Read-only. Listing the agent's tasks exercises exactly the auth and the
 * entitlement that starting one needs, without starting one — a connection
 * test that costs a real agent run and opens a real pull request is not a
 * connection test.
 *
 * Renders only the control and its answer. The row around it belongs to
 * whoever is laying out the page; a component that draws its own row cannot
 * be put in someone else's.
 */
export default function AgentCheck() {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ ok: boolean; detail: string } | null>(null);

  return (
    <div className="inline" style={{ justifyContent: "flex-end", gap: "var(--s2)" }}>
      {result && (
        <span className={`pill ${result.ok ? "ok" : "crit"}`} title={result.detail}>
          {result.ok ? "Reachable" : "Failed"}
        </span>
      )}
      <button
        className="ghost"
        disabled={busy}
        onClick={async () => {
          setBusy(true);
          setResult(null);
          try {
            setResult(await checkImplementationAgent());
          } catch (err) {
            setResult({
              ok: false,
              detail: err instanceof Error ? err.message : String(err),
            });
          } finally {
            setBusy(false);
          }
        }}
      >
        {busy ? "Checking…" : "Check"}
      </button>
    </div>
  );
}
