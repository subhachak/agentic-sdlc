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
        <h2 style={{ marginTop: 0, fontSize: "1rem" }}>When to press it</h2>
        <div className="field">
          <div>
            <div className="field-label">On a new engagement</div>
            <div className="field-help">
              Once. Nothing downstream works until the graph holds the codebase: the design
              phase refuses against an empty graph rather than approving a design nothing
              validated. If the repository has more than one separately buildable unit you
              will be asked which one the execution plane tests — that choice is not a size
              question, it is what stops a QA run being told a change reaches an app it
              does not deploy.
            </div>
          </div>
        </div>
        <div className="field">
          <div>
            <div className="field-label">As code and tests change</div>
            <div className="field-help">
              The same button. It re-reads the repository and reports what moved — new files,
              deleted ones, edges that changed — rather than rebuilding silently. A completed
              run already does this for itself, since it has just changed the codebase; press
              it by hand when the repository moved without a run: a merge, a hotfix, someone
              else&rsquo;s branch.
            </div>
          </div>
        </div>
        <div className="field">
          <div>
            <div className="field-label">What it does besides indexing</div>
            <div className="field-help">
              Two things that used to be separate buttons, because forgetting either
              produced a confident wrong answer rather than an error. It rebuilds the index
              the design agent is grounded in, so the agent is not reasoning about a commit
              that has moved. And it rewrites the copy the execution plane reads: that plane
              runs in client CI with no route to this database, so its graph is a generated
              file, and one describing an older commit scopes the next QA run against the
              wrong code.
            </div>
          </div>
        </div>
      </div>
    </main>
  );
}
