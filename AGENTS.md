# Agentic SDLC — agent guide

A governed pipeline for agent-run software delivery. **Agents propose; a
deterministic core decides; every decision and its evidence is recorded.**
Almost every rule below exists so that sentence stays true under change.

## Layout

| Path | What it is |
|---|---|
| `control-plane/api` | FastAPI + LangGraph. Owns run state, gates, audit trail, context graph. **Never executes agent-authored code.** |
| `control-plane/web` | Next.js console — submit a run, approve at gates. |
| `execution-plane/qa` | The QA phase. **Executes** agent-authored Playwright specs, in CI, holding no write token. |
| `demo-app` | `claims-lite` — the application under test. |

The two planes cannot import each other. What they share is duplicated on
purpose and guarded by a test (I6).

## Invariants

Numbered so a review can cite them. Nearly all are enforced by a test. If you
believe one is wrong, change its test in the same commit and say why in the
message — do not route around it.

**I1 — Deterministic-core purity.** In the control plane, only
`app/adapters/llm/claude_adapter.py` may import `anthropic`, directly or
transitively. Enforced per-module in a clean subprocess by
`tests/test_architecture_purity.py`. This is why `adapters/registry.py`
imports every concrete adapter *lazily, inside its own factory branch* — a
top-level import would pull `anthropic` into every module that touches the
registry. Keep new adapters lazy.
*(The execution plane has its own client, `orchestrator/llm.py`. That is
legitimate — but see I2.)*

**I2 — No model in a pass/fail decision.** Gates are plain Python with no LLM
in the call path. The gates are `core/gate_controller.py`,
`execution-plane/qa/orchestrator/nodes/test_plan.py` (testability) and
`.../nodes/gate.py` (run verdict). An agent may *propose* a plan, a design or
a change; only deterministic code may accept it. Never import `llm.py` into a
gate, and never let a gate's outcome depend on model output.

**I3 — One `interrupt()` call site.** `core/gate_controller.py` only —
currently lines 51 and 82. A pause for a human (`request_gate`) and a pause
for a remote job (`request_external`) are the same mechanism with different
resumers. Do not call `interrupt()` from a node.
LangGraph re-runs a node from its top on resume, so everything before the
interrupt executes twice. Guard writes with the `has_written` dedupe, and
guard side effects (a second CI dispatch) with the unique constraint in
`core/dispatches.py`.

**I4 — Core imports ports, never adapters.** `app/core/**` and
`app/agents/nodes.py` may reference only `app/ports/` Protocol types. Adapter
instances are built once in `main.py`'s lifespan via `adapters/registry.py`
and passed in. Enforced by `tests/test_framework_invariants.py`.

**I5 — Every port has a registry factory.** A port with no
`build_*` function in `adapters/registry.py` is a port a client cannot swap
without editing the platform's entry point. Also enforced: no port declared
and never used, and every adapter implements its *whole* port.

**I6 — `identity.py` is duplicated verbatim across planes.**
`control-plane/api/app/graph/identity.py` and
`execution-plane/qa/orchestrator/identity.py` must stay byte-compatible.
`test_context_graph.py::test_both_planes_derive_the_same_node_id` asserts it.
If they drift, every edge the QA pipeline emits points at a node the control
plane has never heard of — silently. **Change both or neither.**

**I7 — One impact traversal.** All of it lives in `core/impact.py`. There
were once three implementations and they disagreed; a change could pass a
containment check and be tested against a different set. Never re-derive
traversal at a call site. Never roll up to modules *before* traversing —
that inflated blast radius from 0.8% to 13% of a real codebase. `roll_up()`
runs last, for display.

**I8 — Every edge type declares an impact stance.** A new `EdgeType` must
appear in either `SEMANTICS` (how impact propagates) or `NON_PROPAGATING`
(with the reason) in `core/impact.py`. An edge in neither fails
`test_framework_invariants.py`, so adding one forces a decision instead of
being silently untraversed.

**I9 — The ontology is fixed.** `app/graph/ontology.py` node types, edge
types and `SIGNATURES` are not configurable. Clients extend with an `x_`
prefix; extension types are stored and displayed but never reasoned about.
Mapping a client's native identifier onto a core type is the `EntityResolver`
port's job.

**I10 — The QA privilege split is structural.** In
`.github/workflows/agentic-qa.yml`, `qa-run` executes agent-generated specs
with `contents: read` and no write token; `qa-report` holds `issues: write`
and `pull-requests: write` and executes none of that code. They communicate
through a serialized state file. **Never merge these jobs, and never add a
secret to `qa-run` beyond what running tests needs.**
`orchestrator/validate.py` is defense in depth — a text scan, not a sandbox.
The privilege split is the actual control.

**I11 — Node ids are derived, never allocated.** `uuid5` over an escaped
`type|system|external_id`. That is what lets either plane name a criterion
without a round trip, and makes ingestion idempotent. Escaping is not
optional: unescaped, `("code", "a|b")` and `("code|a", "b")` collide. Bump
`IDENTITY_VERSION` if the derivation changes; bumping `NAMESPACE`
re-identifies every node ever written.

**I12 — Comments explain the decision, not the code.** This codebase's
distinctive convention: a non-obvious block says *what went wrong without
it*. "the truthiness test sent refused changes onward"; "nothing in
production ever supplied one, so the check could not fire". Match that
register. Do not add comments that restate the line below them.

## Commands

```bash
# control plane — 727 passed, 4 skipped
cd control-plane/api && uv run pytest -q

# execution plane — 277 passed
cd execution-plane/qa && .venv/bin/python -m pytest tests/ -q
```

`make test-qa` is currently broken: it invokes bare `python`, which does not
exist on macOS here. Use the `.venv/bin/python` form above.

```bash
./run.sh demo      # reset, start both planes, seed the graph, open the console
./run.sh status    # ports, pids, and which adapters are actually live
make preflight     # validate config, DB schema, provider reachability
```

Ports are 8020 (API) and 3020 (console), deliberately not 8000/3000 —
`demo-app` binds :3000 while the QA pipeline runs.

## Conventions

- Python targets 3.11+; the control plane runs under `uv`. `from __future__
  import annotations` at the top of new modules in the execution plane.
- Prefer a frozen `@dataclass` for decision artifacts, and give them an
  `as_dict()` rather than leaking the type across a process boundary.
- Cross-plane payloads are **plain dicts on purpose** — the planes cannot
  share a schema without versioning it. See `_assertions_from` in
  `agents/nodes.py`: a malformed assertion is dropped, never raises.
- New behaviour needs a test in the same commit. The invariants above are
  themselves tests; that is the pattern.
