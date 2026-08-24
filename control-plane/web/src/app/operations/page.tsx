"use client";

import Link from "next/link";
import { HydrationPanel } from "@/components/hydration-panel";

/**
 * Things you do, as opposed to things you set.
 *
 * These were spread across the graph view and a set of scripts, which made
 * first-time setup a matter of knowing where to look. Configuration says what
 * the platform is pointed at; this page is where you act on it.
 */
export default function OperationsPage() {
  return (
    <main className="wide">
      <h1>Operations</h1>
      <p className="muted" style={{ marginTop: "-0.5rem" }}>
        Setup and upkeep for the context graph. What the platform is pointed at lives in{" "}
        <Link href="/config">Configuration</Link> — change it there first, then run these.
      </p>

      <HydrationPanel />

      <div className="card">
        <h2 style={{ marginTop: 0, fontSize: "1rem" }}>When these need running</h2>
        <div className="field">
          <div>
            <div className="field-label">On a new engagement</div>
            <div className="field-help">
              All three, in order. Nothing downstream works until the graph holds the
              codebase: the design phase refuses against an empty graph rather than
              approving a design nothing validated.
            </div>
          </div>
        </div>
        <div className="field">
          <div>
            <div className="field-label">As code and tests change</div>
            <div className="field-help">
              <strong>Update</strong>. A completed run already refreshes the graph itself —
              it has just changed the codebase, so leaving the graph on the previous commit
              would have the next design phase reasoning about code that no longer exists.
              Run it by hand when the repository moved without a run: a merge, a hotfix,
              someone else&rsquo;s branch.
            </div>
          </div>
        </div>
        <div className="field">
          <div>
            <div className="field-label">After any update</div>
            <div className="field-help">
              <strong>Re-export</strong>, if the execution plane should see the change. It
              runs in client CI with no route to this database, so its copy of the graph is
              a generated file rather than a query — and a copy describing an older commit
              scopes the next QA run against the wrong code.
            </div>
          </div>
        </div>
      </div>
    </main>
  );
}
