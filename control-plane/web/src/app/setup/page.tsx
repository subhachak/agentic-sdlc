"use client";

import { useState } from "react";
import ProjectManager from "@/components/project-manager";
import RepositoryPanel from "@/components/repository-panel";
import SettingsPanel, { type SettingsView } from "@/components/settings-panel";

const SECTIONS: { id: SettingsView; label: string; description: string }[] = [
  { id: "engagement", label: "Engagement", description: "Clients, repositories and inferred delivery context" },
  { id: "automation", label: "Agents & execution", description: "Model, implementation, CI and approval behavior" },
  { id: "security", label: "Connections", description: "Credential presence and integration health" },
  { id: "advanced", label: "Advanced", description: "Operational tuning and configuration history" },
];

export default function SetupPage() {
  const [view, setView] = useState<SettingsView>("engagement");
  const [synced, setSynced] = useState(0);
  const current = SECTIONS.find((section) => section.id === view)!;

  return (
    <main>
      <div className="page-head">
        <div className="page-head-copy">
          <span className="eyebrow">Platform management</span>
          <h1>Administration</h1>
          <p>Manage the active client context and the automation shared by every delivery team.</p>
        </div>
      </div>

      <div className="tabs admin-tabs" role="tablist" aria-label="Administration sections">
        {SECTIONS.map((section) => (
          <button
            type="button"
            className="tab-button"
            role="tab"
            aria-selected={view === section.id}
            key={section.id}
            onClick={() => setView(section.id)}
            title={section.description}
          >
            {section.label}
          </button>
        ))}
      </div>

      <div className="page-head" style={{ marginBottom: 16 }}>
        <div className="page-head-copy"><h2 style={{ margin: 0, fontSize: ".95rem" }}>{current.label}</h2><p>{current.description}</p></div>
      </div>

      <div className="admin-layout" role="tabpanel">
        {view === "engagement" && (
          <>
            <ProjectManager />
            <RepositoryPanel onChanged={() => setSynced((value) => value + 1)} />
          </>
        )}
        <SettingsPanel reloadKey={synced} view={view} />
      </div>
    </main>
  );
}
