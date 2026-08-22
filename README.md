# Agentic QA Pipeline — Working Demo

A real, deployable version of the QA phase of an agentic SDLC: a PR
merges to `main`, a GitHub Action fires, and an agent pipeline builds a
test plan from the diff, seeds data, generates or selects Playwright
scripts, runs them, gathers evidence, and either comments PASS on the PR
or files a GitHub issue per failing scenario.

## What's real here

- **Sample app** (`sample-app/`) — a small Next.js app (`/claims`) with a
  real API route and a real feature (a status filter) added via an actual
  git commit, so the pipeline analyzes a real diff, not a mocked one.
- **Orchestrator** (`orchestrator/`) — a LangGraph state graph. Every node
  is a plain Python function over one shared `PipelineState`. Agent calls
  go through Claude (`orchestrator/llm.py`); gates are pure Python with no
  LLM involved (`nodes/test_plan.py`'s testability check, `nodes/gate.py`'s
  pass/fail logic).
- **Test execution** — real Playwright, run via `npx playwright test`
  against a running instance of the sample app. Screenshots, traces, and
  an HTML report are captured on failure.
- **GitHub integration** — real REST API calls (PR comments, issue
  creation) via `orchestrator/github_api.py`, using a `GITHUB_TOKEN`.
- **The workflow** (`.github/workflows/agentic-qa.yml`) — triggers on
  `pull_request: closed` with `merged == true`, matching the "PR merged →
  pipeline runs automatically" requirement exactly.

## Pipeline phases

```
diff_analysis → test_plan ─┬─(gate fails)→ plan_rejected → END
                            └─(gate passes)→ test_data → test_gen
                                → test_run → evidence → gate → report → END
```

1. **diff_analysis** — agent summarizes the PR diff + `features.yaml` context
2. **test_plan** — agent proposes scenarios; deterministic testability gate
   rejects any scenario without a concrete, assertable expected outcome
3. **test_data** — deterministic seeding: guarantees every status/value a
   scenario references actually exists in `sample-app/lib/data-store.json`
4. **test_gen** — for each scenario: select a matching script from
   `test-scripts/manifest.json`, or have the agent generate a new
   Playwright spec into `generated-tests/`
5. **test_run** — `npx playwright test`, real execution
6. **evidence** — indexes screenshots, traces, and the HTML report
7. **gate** — deterministic pass/fail: every planned scenario must have
   run and passed, nothing dropped silently between plan and run
8. **report** — PASS → one PR comment. FAIL → one GitHub issue per failing
   scenario (with evidence pointers) + a summary PR comment linking them

## Running it for real

1. `cd sample-app && npm install && npx playwright install --with-deps chromium`
2. Set repo secrets: `ANTHROPIC_API_KEY` (Actions already has `GITHUB_TOKEN`)
3. Push this repo to GitHub, open a PR against `main` that touches
   `sample-app/` or `features.yaml`, merge it
4. The Action runs automatically — check the PR for the comment, check
   Issues for any defects, download the `qa-evidence-pr-N` artifact for
   screenshots/traces/HTML report

## Running it locally (dry run, no GitHub calls)

```bash
cd sample-app && npm install && npx playwright install --with-deps chromium && cd ..
pip install -r orchestrator/requirements.txt
export ANTHROPIC_API_KEY=sk-...
export DRY_RUN=1   # prints PR comments / issues to stdout instead of calling GitHub

BASE_SHA=$(git rev-list --max-parents=0 HEAD)   # first commit = pre-feature baseline
HEAD_SHA=$(git rev-parse HEAD)                   # latest commit = feature added

python -m orchestrator.run --repo demo/claims-lite --pr-number 1 \
  --base-sha "$BASE_SHA" --head-sha "$HEAD_SHA"
```

## What this deliberately does NOT do yet

- No orchestration across phases beyond QA (Requirements Refinement,
  Architecture, Release are still separate, not-yet-built phases in this design)
- No routing tag for which executor (Playwright/Sauce Labs/Appium) a
  scenario belongs to — this demo is Playwright-only
- No MCP, by design — everything here is native GitHub Actions + REST API,
  matching a common enterprise constraint

## Repo layout

```
sample-app/          Next.js app under test
orchestrator/         LangGraph pipeline (the QA agent)
test-scripts/         Existing Playwright script library + manifest
generated-tests/      Written at runtime — selected + generated specs
evidence/             Written at runtime — results.json, screenshots, traces, HTML report
features.yaml         Stand-in for Requirements Refinement Agent output
.github/workflows/    The trigger
```
