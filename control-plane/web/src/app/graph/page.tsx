"use client";

import { useEffect, useState } from "react";
import { listComponents, seedGraph } from "@/lib/api";
import type { ComponentEntry } from "@/lib/types";

export default function GraphPage() {
  const [components, setComponents] = useState<ComponentEntry[] | null>(null);
  const [repo, setRepo] = useState("");
  const [ref, setRef] = useState("main");
  const [seeding, setSeeding] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    try {
      setComponents((await listComponents()).components);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  useEffect(() => {
    void load();
  }, []);

  async function onSeed() {
    setSeeding(true);
    setError(null);
    setMessage(null);
    try {
      const summary = await seedGraph(repo.trim(), ref.trim() || "main");
      setMessage(
        `Indexed ${summary.components} components and ${summary.files} files, ` +
          `${summary.dependencies} dependencies, ${summary.edges_written} edges written.`
      );
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSeeding(false);
    }
  }

  return (
    <main className="wide">
      <h1>Context graph</h1>
      <p className="muted" style={{ marginTop: "-0.5rem" }}>
        The code half is derived. Point it at a repository and it reads the source, parses
        imports, and works out which components exist and what depends on what. It never
        executes anything it fetches.
      </p>

      <div className="card">
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
              style={{ flex: "2 1 14rem" }}
            />
            <input
              type="text"
              placeholder="main"
              value={ref}
              onChange={(e) => setRef(e.target.value)}
              style={{ flex: "1 1 6rem" }}
            />
            <button onClick={onSeed} disabled={seeding || !repo.trim()}>
              {seeding ? "Indexing..." : "Seed graph"}
            </button>
          </div>
        </div>
        {message && <p style={{ color: "var(--success)", marginBottom: 0 }}>{message}</p>}
        {error && <p style={{ color: "var(--danger)", marginBottom: 0 }}>{error}</p>}
      </div>

      <div className="card">
        <h2 style={{ marginTop: 0, fontSize: "1rem" }}>Components</h2>
        {components === null ? (
          <p className="muted" style={{ marginBottom: 0 }}>Loading...</p>
        ) : components.length === 0 ? (
          <p className="muted" style={{ marginBottom: 0 }}>
            Nothing indexed yet — seed from a repository above.
          </p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Component</th>
                <th className="num">Files</th>
                <th>Depends on</th>
              </tr>
            </thead>
            <tbody>
              {components.map((c) => (
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
