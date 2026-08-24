"use client";

import { useEffect, useState } from "react";
import {
  archiveProject,
  createProject,
  listProjects,
  updateProject,
  type ProjectList,
  type ProjectRecord,
} from "@/lib/api";
import type { SettingEntry } from "@/lib/types";

/**
 * The engagement settings, edited on the project rather than globally.
 *
 * These used to be rows in the settings table, which meant two teams could
 * not hold different answers at the same time — switching client meant
 * overwriting the previous one's repository and branch. They belong to the
 * project record now; the settings table keeps them only as the seed for a
 * new project and the fallback when none answers.
 */
export default function EngagementSection({ specs }: { specs: SettingEntry[] }) {
  const [data, setData] = useState<ProjectList | null>(null);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [creating, setCreating] = useState(false);
  const [newId, setNewId] = useState("");
  const [newName, setNewName] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    try {
      setData(await listProjects());
      setDraft({});
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  useEffect(() => {
    void load();
  }, []);

  const active: ProjectRecord | undefined = data?.projects.find((p) => p.id === data.active);

  async function run(work: () => Promise<string>) {
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      setMessage(await work());
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  if (!data || !active) {
    return (
      <div className="card">
        <p className="muted" style={{ margin: 0 }}>{error ?? "Loading projects…"}</p>
      </div>
    );
  }

  const dirty = Object.keys(draft).length;
  const editable = specs.filter((s) => data.engagement_keys.includes(s.key));

  return (
    <>
      <div className="card">
        <div className="field">
          <div>
            <div className="field-label">Project</div>
            <div className="field-help">
              {active.description || "Everything below belongs to this engagement."}{" "}
              The graph, the runs list and the dashboard are all scoped to it.
            </div>
          </div>
          <div className="field-action" style={{ gap: "0.5rem" }}>
            <button onClick={() => setCreating((c) => !c)} disabled={busy}>
              {creating ? "Cancel" : "New project"}
            </button>
            {active.id !== "default" && (
              <button
                onClick={() =>
                  run(async () => {
                    await archiveProject(active.id);
                    return `Archived ${active.name || active.id}. Its runs and graph are untouched.`;
                  })
                }
                disabled={busy}
              >
                Archive
              </button>
            )}
          </div>
        </div>

        {creating && (
          <div className="field">
            <div>
              <div className="field-label">New engagement</div>
              <div className="field-help">
                The id scopes this project&rsquo;s graph and cannot change afterwards:
                lower-case letters, digits, dot, dash and underscore. It starts from the
                current settings, so correct the fields that differ rather than filling in
                all of them.
              </div>
            </div>
            <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
              <input
                type="text"
                placeholder="acme-claims"
                value={newId}
                onChange={(e) => setNewId(e.target.value)}
                style={{ flex: "1 1 9rem" }}
              />
              <input
                type="text"
                placeholder="Acme — Claims"
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                style={{ flex: "2 1 11rem" }}
              />
              <button
                disabled={busy || !newId.trim()}
                onClick={() =>
                  run(async () => {
                    const created = await createProject(newId.trim(), newName.trim(), "");
                    setCreating(false);
                    setNewId("");
                    setNewName("");
                    return `Created ${created.name}. Switch to it from the nav, then index its repository from Operations.`;
                  })
                }
              >
                Create
              </button>
            </div>
          </div>
        )}
      </div>

      <div className="card">
        {editable.map((spec) => {
          const stored = active.engagement[spec.key];
          const value = draft[spec.key] ?? (stored === null || stored === undefined ? "" : String(stored));
          return (
            <div className="field" key={spec.key}>
              <div>
                <div className="field-label">{spec.label}</div>
                <div className="field-help">
                  <code>{spec.key}</code>
                  {spec.help && <> — {spec.help}</>}
                </div>
              </div>
              <input
                type="text"
                value={value}
                placeholder={spec.placeholder}
                onChange={(e) => setDraft((d) => ({ ...d, [spec.key]: e.target.value }))}
              />
            </div>
          );
        })}

        <div className="field">
          <div>
            <div className="field-label">
              {dirty ? `${dirty} unsaved change${dirty === 1 ? "" : "s"}` : "No changes"}
            </div>
            <div className="field-help">
              Saving re-points the adapters immediately when this is the active project.
            </div>
          </div>
          <div className="field-action">
            <button
              disabled={busy || dirty === 0}
              onClick={() =>
                run(async () => {
                  await updateProject(active.id, { engagement: draft });
                  return `Saved ${dirty} change${dirty === 1 ? "" : "s"} to ${active.name || active.id}.`;
                })
              }
            >
              {busy ? "Saving..." : "Save"}
            </button>
          </div>
        </div>

        {message && <p style={{ color: "var(--success)", marginBottom: 0 }}>{message}</p>}
        {error && <p style={{ color: "var(--danger)", marginBottom: 0 }}>{error}</p>}
      </div>
    </>
  );
}
