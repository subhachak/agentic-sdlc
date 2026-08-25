"use client";

import Link from "next/link";
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
  const engagement = specs.filter((s) => data.engagement_keys.includes(s.key));
  // Three groups, because they are three different kinds of thing and
  // presenting them as one list is what made this page look like twenty
  // questions. Asked: nothing else can supply it. Elsewhere: a control on
  // another page already owns it, and two controls writing one value is how
  // they drift. Derived: it follows from the repository, and only needs
  // touching for the layouts where it does not.
  const ownedElsewhere = engagement.filter((s) => s.owned_by);
  // A field another setting has made inapplicable is not a question either —
  // a working copy path means nothing when the change target is GitHub.
  const applicable = engagement.filter((s) => !s.owned_by && s.relevant !== false);
  const editable = applicable.filter((s) => !s.derived_from && !s.advanced);
  const derivable = applicable.filter((s) => s.derived_from || s.advanced);

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

      {ownedElsewhere.length > 0 && (
        <div className="card">
          <h3 style={{ margin: "0 0 0.15rem", fontSize: "0.9rem" }}>Set from Operations</h3>
          <p className="field-help" style={{ marginTop: 0 }}>
            Chosen when you sync the repository, and shown here so this page and that one
            cannot disagree. <Link href="/operations">Go to Operations</Link>.
          </p>
          {ownedElsewhere.map((spec) => {
            const stored = active.engagement[spec.key];
            const shown = stored === null || stored === undefined || stored === "" ? null : String(stored);
            return (
              <div className="field" key={spec.key}>
                <div>
                  <div className="field-label">{spec.label}</div>
                  <div className="field-help">
                    <code>{spec.key}</code>
                    {spec.help && <> — {spec.help}</>}
                  </div>
                </div>
                <div className="field-action">
                  {shown ? (
                    <code>{shown}</code>
                  ) : (
                    <span className="muted">not set yet — sync to choose</span>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}

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

        {derivable.length > 0 && (
          <details style={{ marginTop: "0.5rem" }}>
            <summary style={{ cursor: "pointer", fontSize: "0.85rem" }}>
              {derivable.length} more, already answered — open only to override
            </summary>
            <p className="field-help" style={{ marginTop: "0.4rem" }}>
              These either follow from the repository being indexed or have a working
              default. The uncommon layouts — CI in a separate repository, a fork as the
              change target, a pipeline reading the graph from elsewhere — are the reason
              they can be set at all, not the reason to ask up front.
            </p>
            {derivable.map((spec) => {
              const stored = active.engagement[spec.key];
              const explicit = stored !== null && stored !== undefined && stored !== "";
              const value =
                draft[spec.key] ?? (explicit ? String(stored) : "");
              return (
                <div className="field" key={spec.key}>
                  <div>
                    <div className="field-label">{spec.label}</div>
                    <div className="field-help">
                      <code>{spec.key}</code>
                      {spec.help && <> — {spec.help}</>}
                      {!explicit && spec.value != null && spec.value !== "" && (
                        <>
                          {" "}
                          Currently <code>{String(spec.value)}</code>, from{" "}
                          <code>{spec.derived_from}</code>.
                        </>
                      )}
                    </div>
                  </div>
                  <input
                    type="text"
                    value={value}
                    placeholder={
                      spec.value != null && spec.value !== ""
                        ? String(spec.value)
                        : spec.placeholder
                    }
                    onChange={(e) => setDraft((d) => ({ ...d, [spec.key]: e.target.value }))}
                  />
                </div>
              );
            })}
          </details>
        )}

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
