"use client";

import { useEffect, useState } from "react";
import {
  activateProject,
  listProjects,
  PROJECTS_CHANGED,
  type ProjectList,
} from "@/lib/api";

export default function ProjectSwitcher() {
  const [data, setData] = useState<ProjectList | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const load = () => listProjects().then(setData).catch(() => setData(null));
    void load();
    window.addEventListener(PROJECTS_CHANGED, load);
    return () => window.removeEventListener(PROJECTS_CHANGED, load);
  }, []);

  const active = data?.projects.find((project) => project.id === data.active);

  if (!data) {
    return (
      <div className="project-control loading" aria-label="Loading active engagement">
        <span className="project-avatar">••</span>
        <span>Loading…</span>
      </div>
    );
  }

  if (data.projects.length < 2) {
    return (
      <div className="project-control" title={active?.description || active?.id || "Default engagement"}>
        <span className="project-avatar" aria-hidden>
          {(active?.name || active?.id || "D").slice(0, 2).toUpperCase()}
        </span>
        <span className="project-control-copy">
          <strong>{active?.name || active?.id || "Default"}</strong>
          <small>Client workspace</small>
        </span>
      </div>
    );
  }

  return (
    <label className="project-control selectable">
      <span className="project-avatar" aria-hidden>
        {(active?.name || active?.id || "D").slice(0, 2).toUpperCase()}
      </span>
      <span className="project-control-copy">
        <span className="sr-only">Active engagement</span>
        <select
          value={data.active}
          disabled={busy}
          onChange={async (event) => {
            setBusy(true);
            try {
              await activateProject(event.target.value);
              window.location.reload();
            } finally {
              setBusy(false);
            }
          }}
        >
          {data.projects.map((project) => (
            <option key={project.id} value={project.id}>
              {project.name || project.id}
            </option>
          ))}
        </select>
        <small>{busy ? "Switching…" : "Client workspace"}</small>
      </span>
    </label>
  );
}
