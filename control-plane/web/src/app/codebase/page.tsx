"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { listModules } from "@/lib/api";
import type { ModuleEntry } from "@/lib/types";

/**
 * What the platform knows about the code, and how well.
 *
 * Read-only on purpose. This is the evidence every gate downstream reasons
 * from — impact, containment, scoping — so it is worth being able to look at
 * without being able to edit it by accident. Changing it means re-reading
 * the repository, which is Setup.
 */
export default function CodebasePage() {
  const [modules, setModules] = useState<ModuleEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listModules()
      .then((r) => setModules(r.modules))
      .catch((err) => setError(err instanceof Error ? err.message : String(err)));
  }, []);

  const total = modules?.reduce((n, m) => n + m.files, 0) ?? 0;
  const edges = modules?.reduce((n, m) => n + m.depends_on.length, 0) ?? 0;

  return (
    <main>
      <div className="page-head">
        <h1>Codebase</h1>
        <p>
          The modules the platform derived and what depends on what. Read by parsing
          imports and route declarations — it never executes anything it fetches.
        </p>
      </div>

      {error && (
        <div className="notice crit">
          <h3>Could not read the graph</h3>
          <p>{error}</p>
        </div>
      )}

      {modules !== null && modules.length > 0 && (
        <div className="stats">
          <div className="stat">
            <span className="stat-label">Modules</span>
            <span className="stat-value">{modules.length}</span>
          </div>
          <div className="stat">
            <span className="stat-label">Files</span>
            <span className="stat-value">{total}</span>
          </div>
          <div className="stat">
            <span className="stat-label">Dependencies</span>
            <span className="stat-value">{edges}</span>
            <span className="stat-note">module to module</span>
          </div>
        </div>
      )}

      <section className="panel">
        <div className="panel-head">
          <div>
            <h2>Modules</h2>
            <p>A directory collapsed to a fixed depth, with the modules it imports from.</p>
          </div>
        </div>
        {modules === null ? (
          <div className="panel-body">
            <p className="muted" style={{ margin: 0 }}>
              Loading…
            </p>
          </div>
        ) : modules.length === 0 ? (
          <div className="panel-body">
            <p className="muted" style={{ margin: 0 }}>
              Nothing indexed yet. <Link href="/setup">Choose a repository in Setup</Link> and
              press Sync.
            </p>
          </div>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Module</th>
                  <th className="num">Files</th>
                  <th>Depends on</th>
                </tr>
              </thead>
              <tbody>
                {modules.map((m) => (
                  <tr key={m.id}>
                    <td>
                      <code>{m.id}</code>
                    </td>
                    <td className="num">{m.files}</td>
                    <td className="muted">
                      {m.depends_on.length === 0 ? (
                        "—"
                      ) : (
                        <span className="inline">
                          {m.depends_on.slice(0, 4).map((d) => (
                            <span key={d.target} className="pill idle">
                              {d.target.split("/").pop()} ×{d.weight}
                            </span>
                          ))}
                          {m.depends_on.length > 4 && (
                            <span className="muted">+{m.depends_on.length - 4}</span>
                          )}
                        </span>
                      )}
                    </td>
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
