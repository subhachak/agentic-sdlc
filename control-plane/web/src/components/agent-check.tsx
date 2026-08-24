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
 * Here rather than left to the first run, because a run reaching the
 * implementation phase and failing on a missing scope is an expensive place
 * to discover it.
 */
export default function AgentCheck({ agent }: { agent: string }) {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ ok: boolean; detail: string } | null>(null);
  // Nothing external to reach, so the button would round-trip to be told what
  // the help text already says.
  const inline = agent === "inline";

  return (
    <div className="field">
      <div>
        <div className="field-label">Reach the implementation agent</div>
        <div className="field-help">
          {agent === "inline"
            ? "This platform writes the change itself — there is nothing external to reach."
            : "Checks that the token can start work as this agent on the configured " +
              "repository. Nothing is started and no pull request is opened."}
        </div>
        {result && !inline && (
          <div
            className="field-help"
            style={{ color: result.ok ? "var(--success)" : "var(--danger)" }}
          >
            {result.detail}
          </div>
        )}
      </div>
      <div className="field-action">
        <button
          disabled={busy || inline}
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
          {busy ? "Checking..." : "Check access"}
        </button>
      </div>
    </div>
  );
}
