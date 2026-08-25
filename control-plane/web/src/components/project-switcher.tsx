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
 * In the masthead rather than on a settings page because it changes what
 * almost every other page means: the graph, the runs list and the overview
 * are all scoped to it. A switcher tucked away in setup would let someone
 * read one client's numbers believing they were another's.
 */
export default function ProjectSwitcher() {
  const [data, setData] = useState<ProjectList | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const load = () => listProjects().then(setData).catch(() => setData(null));
    void load();
    window.addEventListener(PROJECTS_CHANGED, load);
    return () => window.removeEventListener(PROJECTS_CHANGED, load);
  }, []);

  // One project is not a choice, and a dropdown with a single option reads
  // as a setting someone forgot to fill in.
  if (!data || data.projects.length < 2) return null;

  return (
    <select
      aria-label="Engagement"
      value={data.active}
      disabled={busy}
      style={{ fontSize: "0.85rem", padding: "0.25rem 0.4rem" }}
      onChange={async (e) => {
        setBusy(true);
        try {
          await activateProject(e.target.value);
          window.location.reload();
        } finally {
          setBusy(false);
        }
      }}
    >
      {data.projects.map((p) => (
        <option key={p.id} value={p.id}>
          {p.name || p.id}
        </option>
      ))}
    </select>
  );
}
