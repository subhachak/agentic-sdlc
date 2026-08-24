"use client";

import { useEffect, useState } from "react";
import {
  activateProject,
  listProjects,
  PROJECTS_CHANGED,
  type ProjectList,
} from "@/lib/api";

/**
 * Which engagement the console is working on.
 *
 * In the nav rather than on a settings page because it changes what almost
 * every other page means: the graph, the runs list and the dashboard are all
 * scoped to it. A switcher tucked away in configuration would let someone
 * read one client's numbers believing they were another's.
 */
export default function ProjectSwitcher() {
  const [data, setData] = useState<ProjectList | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const load = () =>
      listProjects()
        .then(setData)
        .catch((err) => setError(err instanceof Error ? err.message : String(err)));

    void load();
    // The editor lives on another page. Without this, a project created there
    // is missing from this list until someone reloads — and the one place it
    // needs to appear is the control that switches to it.
    window.addEventListener(PROJECTS_CHANGED, load);
    return () => window.removeEventListener(PROJECTS_CHANGED, load);
  }, []);

  async function onSwitch(id: string) {
    if (!data || id === data.active) return;
    setBusy(true);
    setError(null);
    try {
      const result = await activateProject(id);
      if (result.warning) window.alert(result.warning);
      // A full reload rather than a router refresh: every page on screen is
      // scoped to the project that just changed, and re-fetching only the
      // active route would leave the rest showing the previous engagement.
      window.location.reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setBusy(false);
    }
  }

  if (error) {
    return (
      <span className="project-switcher" title={error}>
        <span className="muted">projects unavailable</span>
      </span>
    );
  }

  if (!data) {
    return <span className="project-switcher muted">…</span>;
  }

  return (
    <span className="project-switcher">
      <label htmlFor="active-project" className="sr-only">
        Active project
      </label>
      <select
        id="active-project"
        value={data.active}
        disabled={busy}
        onChange={(e) => void onSwitch(e.target.value)}
      >
        {data.projects.map((project) => (
          <option key={project.id} value={project.id}>
            {project.name || project.id}
          </option>
        ))}
      </select>
    </span>
  );
}
