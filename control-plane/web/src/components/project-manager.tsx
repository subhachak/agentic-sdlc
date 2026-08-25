"use client";

import { useEffect, useState } from "react";
import {
  activateProject,
  archiveProject,
  createProject,
  listProjects,
  PROJECTS_CHANGED,
  type ProjectList,
} from "@/lib/api";

function slug(value: string) {
  return value
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "")
    .slice(0, 48);
}

export default function ProjectManager() {
  const [data, setData] = useState<ProjectList | null>(null);
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [confirmArchive, setConfirmArchive] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    try {
      setData(await listProjects());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }

  useEffect(() => { void load(); }, []);

  async function addProject() {
    const id = slug(name);
    if (!id) return;
    setBusy("create");
    setError(null);
    try {
      await createProject(id, name.trim(), description.trim());
      await activateProject(id);
      setName("");
      setDescription("");
      setCreating(false);
      setMessage(`${name.trim()} created with the current platform defaults.`);
      window.dispatchEvent(new Event(PROJECTS_CHANGED));
      window.location.reload();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(null);
    }
  }

  return (
    <section className="panel">
      <div className="panel-head">
        <div>
          <h2>Client engagements</h2>
          <p>Each workspace keeps its own repository context and engagement-specific defaults.</p>
        </div>
        <div className="panel-head-end">
          <button type="button" className="secondary" onClick={() => setCreating((current) => !current)}>
            {creating ? "Cancel" : "＋ New engagement"}
          </button>
        </div>
      </div>
      <div className="panel-body">
        {!data ? <p className="muted">Loading engagements…</p> : (
          <div className="project-grid">
            {data.projects.map((project) => {
              const active = project.id === data.active;
              return (
                <article className={`project-card ${active ? "active" : ""}`} key={project.id}>
                  <div className="project-card-head">
                    <span className="project-card-avatar" aria-hidden>{(project.name || project.id).slice(0, 2).toUpperCase()}</span>
                    <div className="grow">
                      <h3>{project.name || project.id}</h3>
                      <p>{project.description || "No engagement description"}</p>
                    </div>
                    {active && <span className="pill ok">Active</span>}
                  </div>
                  <div className="project-card-meta">
                    {project.engagement.code_index_repo && <span className="dependency-chip">{String(project.engagement.code_index_repo)}</span>}
                    {project.engagement.target_environment && <span className="dependency-chip">{String(project.engagement.target_environment)}</span>}
                  </div>
                  {!active && (
                    <div className="project-card-actions">
                      <button
                        type="button"
                        className="secondary"
                        disabled={Boolean(busy)}
                        onClick={async () => {
                          setBusy(project.id);
                          try { await activateProject(project.id); window.location.reload(); }
                          catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); setBusy(null); }
                        }}
                      >
                        {busy === project.id ? "Switching…" : "Open workspace"}
                      </button>
                      {project.id !== "default" && (
                        confirmArchive === project.id ? (
                          <>
                            <button type="button" className="danger-secondary" onClick={() => setConfirmArchive(null)}>Keep</button>
                            <button
                              type="button"
                              className="danger"
                              disabled={Boolean(busy)}
                              onClick={async () => {
                                setBusy(`archive-${project.id}`);
                                try { await archiveProject(project.id); setConfirmArchive(null); await load(); }
                                catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); }
                                finally { setBusy(null); }
                              }}
                            >
                              Archive
                            </button>
                          </>
                        ) : <button type="button" className="quiet" onClick={() => setConfirmArchive(project.id)}>Archive</button>
                      )}
                    </div>
                  )}
                </article>
              );
            })}
          </div>
        )}

        {creating && (
          <div className="inline-create">
            <div className="inline-create-grid">
              <label><span className="field-label">Client or engagement name</span><input type="text" value={name} placeholder="Northstar Claims" autoFocus onChange={(event) => setName(event.target.value)} /></label>
              <label><span className="field-label">Description <span className="muted">(optional)</span></span><input type="text" value={description} placeholder="Claims modernization delivery workspace" onChange={(event) => setDescription(event.target.value)} /></label>
              <button type="button" disabled={!slug(name) || busy === "create"} onClick={() => void addProject()}>{busy === "create" ? "Creating…" : "Create and open"}</button>
            </div>
            <span className="field-help">Workspace ID <code>{slug(name) || "generated-from-name"}</code> · platform defaults will be inherited automatically.</span>
          </div>
        )}
        {message && <div className="notice ok" style={{ marginTop: 14, marginBottom: 0 }}><h3>Engagement ready</h3><p>{message}</p></div>}
        {error && <div className="notice crit" role="alert" style={{ marginTop: 14, marginBottom: 0 }}><h3>Could not update engagements</h3><p>{error}</p></div>}
      </div>
    </section>
  );
}
