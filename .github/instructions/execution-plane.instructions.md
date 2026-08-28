---
name: 'QA execution plane'
description: 'The QA phase — deterministic gates, untrusted code execution, and the privilege split.'
applyTo: 'execution-plane/**'
---

# You are in the execution plane

This half **executes** agent-authored code. It runs in CI where the
repository and credentials already live, and it holds no write token while
doing so.

## The privilege split is the security control (I10)

`.github/workflows/agentic-qa.yml` splits into `qa-run` (`contents: read`,
executes generated specs) and `qa-report` (holds `issues: write`, executes
none of it), communicating through a serialized state file. **Never merge
them. Never add a secret to `qa-run` beyond what running tests needs.**

`orchestrator/validate.py` is defense in depth — a regex scan over generated
TypeScript, explicitly not a sandbox. Improving it is welcome; treating it as
the control is not.

## Gates are plain Python (I2)

`nodes/test_plan.py` (testability) and `nodes/gate.py` (run verdict) contain
no LLM call and must not gain one. An agent proposes scenarios; deterministic
code decides whether they are testable, and the rejection reasons are fed
back for a bounded number of attempts.

Rules the gate encodes, which are easy to erode:

- Only `("expected", "passed")` count as a pass. `flaky` and `skipped` do not.
- **Only passing tests count as coverage.** A spec that ran and failed
  demonstrates the opposite; counting it would let a broken change report its
  blast radius as covered.
- **Observation beats declaration.** A manifest's `covers_modules` is
  somebody's assertion; the files a spec actually requested are the run's own
  account. Edges carry `runtime-observed` or `declared` accordingly — never
  neither.
- Fail closed on: dangling coverage, coverage mismatches, and a shared data
  store mutated during a parallel run.
- Coverage gaps **report** rather than block by default
  (`QA_REQUIRE_FULL_COVERAGE=1` makes them blocking). Refusing every change to
  a codebase with an unfinished regression suite makes the tool uninstallable.

## Selection and the ratchet

- `selection.py`: a script is **excluded** only where its coverage was
  observed at runtime. A hand-written claim is enough to keep a script, never
  enough to skip one. Untrustworthy scope — no assessment, a stale graph, a
  low capture rate, unknown files — escalates to the full library, naming the
  reason.
- `known_failing.py`: declared debt may shrink, never grow. The pipeline
  **must not write `known-failing.json` into the repository** — it proposes
  into `evidence/` so adopting the record is a commit somebody reviews. A
  missing record means "not adopted", not "nothing may fail".
- `baseline.py`: a failure that predates the change is not a regression.

## Node shape

Plain functions `run(state: PipelineState) -> PipelineState`, returning
`{**state, ...}`. The graph ends at the gate; reporting lives outside it, in
the job that holds the token.

## Cross-plane contract

`context.py` validates `export_version` against `SUPPORTED_EXPORT_VERSIONS`
and raises `IncompatibleGraphExport` rather than trusting the shape — a
versioned artefact nobody validates is an unversioned artefact. Node ids are
derived with `orchestrator/identity.py`, which is **duplicated verbatim** from
the control plane (I6). Never edit one copy alone.

Run the suite with `.venv/bin/python -m pytest tests/ -q` from
`execution-plane/qa`, or `make test-qa` from the root, which creates that venv
on first use.
