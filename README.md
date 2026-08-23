# Agentic SDLC

A governed pipeline for agent-run software delivery. Agents propose; a
deterministic core decides; every decision and its evidence is recorded.

The repository is laid out as the architecture: a **control plane** that owns
decisions and evidence, and an **execution plane** that runs the actual work
where the code and credentials already live.

```
control-plane/     decides — run state, gates, audit trail, context graph
  api/               FastAPI + LangGraph, ports and adapters, GateController
  web/               Next.js console: submit a run, approve at gates
execution-plane/   executes — one directory per lifecycle phase
  qa/                the QA phase: plan from a diff, run Playwright, file defects
demo-app/          claims-lite — the application under test
scripts/           local demo drivers
```

## The two planes

The **control plane** is long-lived. It holds run state, pauses for human
approval at gate boundaries, records an audit entry per node execution, and
reaches every external system through a port with a swappable adapter
(`control-plane/api/app/ports/`). It never executes agent-authored code.

The **execution plane** is ephemeral. It runs inside CI — the client's CI, in
a real deployment — where the repository, the runners, the credentials and
the compliance controls already exist. It executes agent-authored code and
holds no write credentials while doing so.

Between them sits a **context graph**. Phases assert typed relationships —
this criterion is verified by that scenario, which ran as that script — at
the moment their gate decides, so the graph fills itself as a byproduct of
governance rather than through a separate ingestion job. It holds identity
and relationships only: requirement text stays in the client's tracker, code
stays in the repository, and node ids are derived rather than allocated so
both planes name the same thing without a round trip.

That is what makes questions like "which acceptance criteria have never
reached a passing test" a query rather than an assertion — and what lets the
QA phase widen regression scope from what a diff touched to what depends on
what it touched.

The code half of the graph is derived, not written by hand. Point it at a
repository and it fetches the source archive, parses imports, and works out
which components exist and what depends on what:

```bash
make seed-preview REPO=owner/name    # index without writing
make seed-graph   REPO=owner/name    # index and seed the graph
```

It reads source and parses imports; it never executes anything it fetches.

Today these are two working halves that do not yet talk to each other. The
seam between them — dispatch a phase into CI, correlate a signed callback
back to a run — is the next thing to build.

## The QA phase is real

`execution-plane/qa/` is not a stub. On a merged pull request it analyses the
real diff, plans test scenarios, seeds fixtures the plan depends on, selects
an existing Playwright script or generates a new one, runs the suite against
a built `demo-app/`, captures screenshots and traces, and either comments
PASS on the pull request or files one GitHub issue per failing scenario.

Two properties are worth knowing before reading the code:

- **No model is ever in a pass/fail decision.** The testability gate
  (`nodes/test_plan.py`) and the run gate (`nodes/gate.py`) are plain Python
  with no LLM involved, and both are covered by tests.
- **The job that executes agent-generated specs holds no write token.** The
  workflow splits into `qa-run` (executes, `contents: read`) and `qa-report`
  (writes to GitHub, executes none of it), communicating through a
  serialized state file.

## Running it

Requires [uv](https://docs.astral.sh/uv/), Node.js 20+, and Python 3.11+.

```bash
cp .env.example .env          # defaults to the mock LLM adapter, no API key needed
```

If keys are already configured in another project on this machine:

```bash
./run.sh keys                 # show what is available, by name and source
./run.sh keys import          # copy them into .env and switch to the claude adapter
./run.sh keys import --github # also set the Actions secret on this repo
```

Values are moved file to file and never printed; `.env` is written mode 600
and is gitignored. Without any key the platform still runs — the model
provider defaults to a deterministic mock.

Then, from the repository root:

```bash
./run.sh demo          # reset, start both, seed the graph, open the console
./run.sh start         # just start (API on :8020, console on :3020)
./run.sh status        # ports, pids, and which adapters are actually live
./run.sh stop
```

Ports avoid 8000/3000 deliberately: `demo-app` binds :3000 while the QA
pipeline runs, and other projects on a typical machine take those. Override
with `API_PORT` / `WEB_PORT`.

The `make` targets still work for individual pieces:

```bash
make api     # control plane API
make web     # console
make test    # both test suites
```

The console has four views: a **dashboard** showing what is running, what is
waiting on a person versus on CI, and how many acceptance criteria have
reached a passing test; the **runs** list and detail; the **context graph**,
where you point it at a repository and watch the component structure appear;
and **configuration**.

Configuration lives in the control plane, not only in `.env`. Adapter choices
and thresholds are editable in the console and applied by rebuilding the
adapters — no restart, because the registry is already a pure function of
settings. Secrets are the exception: they stay in the environment, are
reported as present or absent, and are never read back or accepted through
the API. Every change is recorded with its previous value.

For the QA pipeline on its own, against the demo app:

```bash
export ANTHROPIC_API_KEY=sk-...
make qa-demo                  # dry run — prints what it would post to GitHub
```

## Where to read next

- `control-plane/README.md` — the governance core, ports, and adapter swap
- `execution-plane/qa/orchestrator/` — the QA agent, node by node
- `execution-plane/qa/tests/` — what the deterministic gates are held to
