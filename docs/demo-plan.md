# End-to-end demo on Fronei — plan

Jira story → design → implementation → QA → gated merge → production, with
rollback.

## Shape of it

Deploy is **not** a platform API call. Gate 3 approval merges the PR; the
merge triggers Fronei's existing auto-deploy (Vercel for `apps/web`, Railway
for `apps/api` + DB). The platform drives the pipeline through the same door
a human would, then *observes* what happened.

That matters for the governance story: nothing routes around existing CI or
review, so the demo shows the controls working rather than replacing them.

BuildDeploy therefore does three things, not one:

    deploy()    merge the approved PR, return a receipt
    check()     find the deployment that merge produced, report health
    rollback()  re-promote the previous Vercel deployment

## Rollback, proven first

Non-negotiable ordering: **rollback is exercised before an agent-authored
change goes anywhere near production.** Deploy something trivial by hand,
roll it back, confirm the live site reverted. If that is not clean, the demo
stops at Gate 3 and records the decision instead of deploying.

Three layers, cheapest first:

| | Mechanism | Time | Restores |
|---|---|---|---|
| 1 | Re-promote previous Vercel deployment | seconds | the live UI |
| 2 | `git revert` the merge, push | minutes | the repo, and both hosts |
| 3 | Retract the release assertions | instant | the graph |

Layer 1 is what you want between demo runs. Layer 2 is the reset. Layer 3
works because `retract` supersedes rather than deletes, so rolling back a
run leaves the history that it happened.

One wrinkle to decide when we get there: a merge redeploys **both** hosts. A
change confined to `apps/web` only alters the UI, but Railway rebuilds an
identical API anyway. Layer 1 covers the UI; layer 2 covers both.

`./run.sh rollback` wraps layers 1 and 2 — one command under demo pressure,
not three API calls from memory.

---

## Work, in dependency order

### Phase 0 — prove the ground (no platform involved)

- [ ] Confirm the Vercel deployments API and rollback work with a token you supply
- [ ] Manual deploy → manual rollback → verify the live site reverted
- [ ] `./run.sh rollback`
- [ ] Decide: does rollback need to cover Railway too, or is UI-only enough

**Exit:** rollback demonstrably works, without an agent in the loop.

### Phase 1 — point the platform at Fronei

- [ ] Jira credentials in `.env` (you set them; I never handle them)
- [ ] `/api/config/check-agent` verifies the Jira connection
- [ ] `requirements_source_adapter=jira`, a story with acceptance criteria
- [ ] Confirm criteria arrive as graph nodes with their Jira ids

**Exit:** a real story flows into the graph from the system of record.

Nothing to build. The Jira adapter and the index already exist — Fronei is
indexed at 98.8% capture with retrieval built.

### Phase 2 — make QA able to see Fronei *(small code)*

`FEATURES_FILE`, `LIBRARY_DIR`, `GENERATED_DIR` and `DATA_STORE` are
hardcoded relative to `demo-app`. Only `QA_APP_ROOT` and `QA_CODE_GRAPH` are
overridable, so QA physically cannot point at another app.

- [ ] Make all of them overridable, same pattern as the existing two
- [ ] `QA_APP_ROOT=apps/web`

**Exit:** the QA plane can run against Fronei's checkout.

### Phase 3 — Fronei's regression library *(content, not code)*

Fronei already has `apps/web/e2e/{admin,agent}.spec.ts` and a live suite.
Those become the regression library; what is missing is the manifest that
maps spec → modules covered, which is what drives required-regression
selection.

- [ ] `manifest.json` mapping Fronei's specs to module ids from the index
- [ ] Acceptance criteria: from the Jira story rather than a hand-written
      `features.yaml`, which is the point of Phase 1

**Exit:** a change to a shared lib selects the right existing regressions.

### Phase 4 — test data *(small code)*

Fronei's e2e uses Playwright **route mocking** (`e2e/api-mocks.ts`), not a
database. Each test installs its own routes, so isolation is per-scenario by
construction.

- [ ] A `RouteMockTestData` provider declaring `scenario` isolation

**Exit:** QA runs Fronei's suite in parallel — `workers_for` already handles
that once the provider says so.

### Phase 5 — the workflow in Fronei's repo *(needs a PR to Fronei)*

- [ ] Install `agentic-qa.yml`, adapted to Fronei's layout
- [ ] `check_access` confirms it exists and declares the four contract inputs

**Exit:** the control plane can dispatch QA into Fronei's CI.

### Phase 6 — BuildDeploy: merge, observe, roll back *(medium code)*

- [ ] `deploy()` merges the approved PR via the GitHub API
- [ ] `check()` finds the Vercel deployment for that commit, reports health
- [ ] `rollback()` re-promotes the previous deployment
- [ ] Wire `RollbackCapable` — already declared as an optional capability

**Exit:** Gate 3 approval merges, the deploy is observed, and rollback is one
call.

### Phase 7 — dry run, then the demo

- [ ] Full run end to end with Gate 3 **declined** — proves the refusal path
- [ ] Full run with Gate 3 approved, then roll back
- [ ] Only then: the demo

---

## The story to pick

`BACKLOG.md` is tech debt — mostly large refactors, and a 4,915-line god
file is not a demo. Better to write a small Jira story against the shared
lib, where the impact engine has something real to say.

Run through the actual engine, not estimated:

| Candidate | Files reached | Modules | Test obligations |
|---|---|---|---|
| `app/lib/format.ts` | 19 | 5 | 19 |
| `app/lib/api.ts` | 27 | 4 | 27 |

**Recommend `format.ts`.** It reaches five modules rather than four, so the
blast radius is wider in the dimension that reads well; it already has
`format.test.ts`, so there is existing coverage to select as a required
regression rather than only generated tests; formatting is visible in the
UI, so "here is the change, live" is a sentence you can say while pointing
at a screen; and a formatting change is small enough that an agent will get
it right, which matters when the audience is watching.

`api.ts` reaches more files but is the API client — a mistake there breaks
every page, which is the wrong kind of exciting for a live demo.

## What this demo will not show

Stated so nobody discovers it live:

- **No dispatched design or test-authoring agent.** Those ports exist and
  their `pending` paths have never run against a real provider. The demo
  uses the in-process agents.
- **`TestManagement` writes to a JSON file**, not Xray or TestRail.
- **Evidence is a CI run URL**, not a signed artifact.
- **Rollback covers the UI fast and both hosts slowly.** There is no
  single-call rollback of a Railway deploy in the plan yet.
