"use client";

import { useCallback, useEffect, useState } from "react";
import {
  exportGraph,
  hydrationStatus,
  rebuildRetrieval,
  refreshGraph,
  seedGraph,
  type HydrationStatus,
  type HydrationStep,
} from "@/lib/api";

/**
 * First-time setup, and every update after it.
 *
 * "Is it set up" has more than one answer. The graph can be indexed while
 * retrieval is unbuilt and the execution plane's copy describes last week's
 * commit — and each of those fails differently, so each is a step with its
 * own state rather than one button that either worked or did not.
 */

type Busy = "seed" | "refresh" | "export" | "retrieval" | null;

function StepRow({
  step,
  action,
  label,
  busy,
  disabled,
}: {
  step: HydrationStep;
  action: () => void;
  label: string;
  busy: boolean;
  disabled: boolean;
}) {
  const blocked = step.blocked_by !== null;
  const state = step.ready ? "ready" : blocked ? "blocked" : "pending";
  const colour =
    state === "ready" ? "var(--success)" : state === "blocked" ? "var(--muted)" : "var(--warning)";

  return (
    <div className="field">
      <div style={{ minWidth: 0 }}>
        <div className="field-label" style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
          <span aria-hidden style={{ color: colour, fontSize: "1.1em", lineHeight: 1 }}>
            {step.ready ? "●" : "○"}
          </span>
          {step.title}
          <span className="sr-only">{state}</span>
        </div>
        <div className="field-help">{step.detail}</div>
        {step.quality && !step.quality.sufficient && (
          <div className="field-help" style={{ color: "var(--danger)" }}>
            Only {(step.quality.internal_capture_rate * 100).toFixed(1)}% of internal imports
            resolved. Below 80% the design phase refuses, because an impact set derived from
            this many missing edges cannot be trusted.
            {step.quality.most_missed.length > 0 && (
              <> Unresolved: {step.quality.most_missed.map(([spec]) => spec).join(", ")}</>
            )}
          </div>
        )}
      </div>
      <div className="field-action">
        <button onClick={action} disabled={busy || disabled || blocked}>
          {busy ? "Working..." : label}
        </button>
      </div>
    </div>
  );
}

export function HydrationPanel({ onChanged }: { onChanged?: () => void }) {
  const [status, setStatus] = useState<HydrationStatus | null>(null);
  const [repo, setRepo] = useState("");
  const [ref, setRef] = useState("main");
  const [scope, setScope] = useState("demo-app");
  const [busy, setBusy] = useState<Busy>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const next = await hydrationStatus();
      setStatus(next);
      if (!repo && next.provenance.repo) setRepo(next.provenance.repo);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [repo]);

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function run(kind: Exclude<Busy, null>, work: () => Promise<string>) {
    setBusy(kind);
    setError(null);
    setMessage(null);
    try {
      setMessage(await work());
      await load();
      onChanged?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  }

  const step = (id: string) => status?.steps.find((s) => s.id === id);
  const indexStep = step("index");
  const retrievalStep = step("retrieval");
  const exportStep = step("export");
  const noRepo = !repo.trim();

  return (
    <div className="card">
      <h2 style={{ marginTop: 0, fontSize: "1rem" }}>
        Setup{" "}
        {status && (
          <span
            className="muted"
            style={{ fontWeight: 400, color: status.hydrated ? "var(--success)" : "var(--warning)" }}
          >
            — {status.hydrated ? "hydrated" : "incomplete"}
          </span>
        )}
      </h2>
      <p className="field-help" style={{ marginTop: "-0.4rem" }}>
        Run these in order the first time. After that, <strong>Update</strong> re-reads the
        repository and reports what moved — new files, deleted ones, edges that changed — rather
        than rebuilding silently.
      </p>

      <div className="field">
        <div>
          <div className="field-label">Repository</div>
          <div className="field-help">Public, or private with a token configured</div>
        </div>
        <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
          <input
            type="text"
            placeholder="owner/name"
            value={repo}
            onChange={(e) => setRepo(e.target.value)}
            style={{ flex: "2 1 12rem" }}
          />
          <input
            type="text"
            placeholder="main"
            value={ref}
            onChange={(e) => setRef(e.target.value)}
            style={{ flex: "1 1 5rem" }}
          />
        </div>
      </div>

      {indexStep && (
        <StepRow
          step={indexStep}
          busy={busy === "seed"}
          disabled={noRepo}
          label={indexStep.ready ? "Re-index" : "Index"}
          action={() =>
            run("seed", async () => {
              const s = await seedGraph(repo.trim(), ref.trim() || "main");
              return `Indexed ${s.repo} at ${(s.commit_sha ?? "unpinned").slice(0, 7)}: ${
                s.modules
              } modules, ${s.files} files, ${s.file_imports} import edges. Captured ${(
                s.resolution.internal_capture_rate * 100
              ).toFixed(1)}% of internal imports.`;
            })
          }
        />
      )}

      {indexStep && (
        <div className="field">
          <div>
            <div className="field-label">Update from the repository</div>
            <div className="field-help">
              Re-reads the source and applies only what differs. Use this as code and tests
              change; it names what moved instead of replacing the graph wholesale.
            </div>
          </div>
          <div className="field-action">
            <button
            onClick={() =>
              run("refresh", async () => {
                const s = await refreshGraph(repo.trim(), ref.trim() || "main");
                const d = s.delta;
                if (d.edges_added === 0 && d.edges_removed === 0) {
                  return `Already current at ${(s.commit_sha ?? "unpinned").slice(0, 7)} — ${
                    d.unchanged
                  } edges unchanged.`;
                }
                return `Updated to ${(s.commit_sha ?? "unpinned").slice(0, 7)}: ${
                  d.edges_added
                } edge(s) added, ${d.edges_removed} removed, ${d.nodes_removed} file(s) dropped, ${
                  d.unchanged
                } unchanged.`;
              })
            }
            disabled={busy !== null || noRepo || !indexStep.ready}
          >
            {busy === "refresh" ? "Updating..." : "Update"}
            </button>
          </div>
        </div>
      )}

      {retrievalStep && (
        <StepRow
          step={retrievalStep}
          busy={busy === "retrieval"}
          disabled={false}
          label={retrievalStep.ready ? "Rebuild" : "Build"}
          action={() =>
            run("retrieval", async () => {
              const s = await rebuildRetrieval();
              return `Retrieval index built: ${s.chunks} chunks at ${(
                s.built_for ?? "unpinned"
              ).slice(0, 7)}.`;
            })
          }
        />
      )}

      {exportStep && (
        <>
          <StepRow
            step={exportStep}
            busy={busy === "export"}
            disabled={false}
            label={exportStep.ready ? "Re-export" : "Export"}
            action={() =>
              run("export", async () => {
                const s = await exportGraph(scope.trim() || "demo-app");
                return `Exported ${s.modules} modules and ${s.routes} routes at ${(
                  s.commit_sha ?? "unpinned"
                ).slice(0, 7)} to ${s.path}.`;
              })
            }
          />
          <div className="field">
            <div>
              <div className="field-label">Export scope</div>
              <div className="field-help">
                The subtree the execution plane tests. Not only a size question: a QA run
                testing the app should not be told a change reaches the control plane.
              </div>
            </div>
            <input
              type="text"
              value={scope}
              onChange={(e) => setScope(e.target.value)}
              style={{ flex: "1 1 8rem" }}
            />
          </div>
        </>
      )}

      {message && <p style={{ color: "var(--success)", marginBottom: 0 }}>{message}</p>}
      {error && <p style={{ color: "var(--danger)", marginBottom: 0 }}>{error}</p>}
    </div>
  );
}
