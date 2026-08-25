"use client";

import { useState } from "react";
import RepositoryPanel from "@/components/repository-panel";
import SettingsPanel from "@/components/settings-panel";

/**
 * Setup — formerly Operations and Configuration.
 *
 * They were the same subject split by verb: what the platform is pointed at,
 * and pointing it. Nobody arrives knowing whether choosing a repository is a
 * setting or an action, and the split put a repository field on both pages,
 * where they promptly disagreed with each other.
 *
 * Ordered by what someone actually does: pick the repository, sync, then the
 * handful of things the repository cannot tell us.
 */
export default function SetupPage() {
  // A sync changes what the settings resolve to — it writes the repository
  // and the export scope — so the settings below re-read when it finishes.
  const [synced, setSynced] = useState(0);

  return (
    <main>
      <div className="page-head">
        <h1>Setup</h1>
        <p>
          Point the platform at a codebase and it works out the rest. What is left here is
          what nothing else can supply.
        </p>
      </div>

      <RepositoryPanel onChanged={() => setSynced((n) => n + 1)} />
      <SettingsPanel reloadKey={synced} />
    </main>
  );
}
