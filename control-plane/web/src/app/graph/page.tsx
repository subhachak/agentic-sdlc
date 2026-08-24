"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { listModules } from "@/lib/api";
import type { ModuleEntry } from "@/lib/types";

export default function GraphPage() {
  const [modules, setModules] = useState<ModuleEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    try {
      setModules((await listModules()).modules);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  useEffect(() => {
    void load();
  }, []);

  return (
    <main className="wide">
      <h1>Context graph</h1>
      <p className="muted" style={{ marginTop: "-0.5rem" }}>
        What the platform knows about the codebase: which modules exist, and what depends
        on what. Derived by reading source and parsing imports — it never executes anything
        it fetches. To index, update or export it, see <Link href="/operations">Operations</Link>.
      </p>

      {error && (
        <p style={{ color: "var(--danger)" }}>{error}</p>
      )}

      <div className="card">
        <h2 style={{ marginTop: 0, fontSize: "1rem" }}>Modules</h2>
        {modules === null ? (
          <p className="muted" style={{ marginBottom: 0 }}>Loading...</p>
        ) : modules.length === 0 ? (
          <p className="muted" style={{ marginBottom: 0 }}>
            Nothing indexed yet — index a repository from Operations.
          </p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Module</th>
                <th className="num">Files</th>
                <th>Depends on</th>
              </tr>
            </thead>
            <tbody>
              {modules.map((c) => (
                <tr key={c.id}>
                  <td><code>{c.id}</code></td>
                  <td className="num">{c.files}</td>
                  <td className="muted">
                    {c.depends_on.length === 0
                      ? "—"
                      : c.depends_on
                          .slice(0, 4)
                          .map((d) => `${d.target.split("/").pop()} (${d.weight})`)
                          .join(", ")}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </main>
  );
}
