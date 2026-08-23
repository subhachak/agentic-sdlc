# Control plane

**A prototype, not a production system.** It runs a governed agentic SDLC
pipeline end to end on a laptop. This layer is the skeleton:
six swappable interface contracts, a LangGraph state machine with trivial
stub/echo node logic, a central gate controller enforcing human approval at
every phase boundary, and an audit trail proving every node execution and
gate decision. Real agent reasoning and the eval harness are still to come; the QA
phase is implemented for real under `execution-plane/qa/`.

## Architecture

- **Agents reason at the edges only.** A deterministic core (`control-plane/api/app/core/`)
  governs all state transitions and gating. Agents cannot self-approve or
  auto-progress the pipeline.
- **Humans approve at every phase boundary** — via `GateController`
  (`control-plane/api/app/core/gate_controller.py`), the single place in the codebase
  that calls LangGraph's `interrupt()`.
- **Ports and adapters.** Six interfaces (`control-plane/api/app/ports/`) each have
  exactly one demo-default adapter (`control-plane/api/app/adapters/`). Adapter
  selection is config-driven (`.env` → `LLM_PROVIDER_ADAPTER=mock|claude`)
  — never hardcoded imports scattered through node code.
- **Deterministic-core purity is enforced by a test**, not just a comment:
  `control-plane/api/tests/test_architecture_purity.py` asserts that only
  `app/adapters/llm/claude_adapter.py` imports `anthropic`, anywhere in the
  codebase.

See `control-plane/api/app/` for the module layout: `ports/`, `adapters/`, `core/`,
`agents/`, `models/`, `routers/`, `schemas/`.

## Running it locally

Requires [uv](https://docs.astral.sh/uv/) and Node.js 20+.

```bash
cp .env.example .env      # defaults to the mock LLM adapter — no API key needed
cd control-plane/api && uv sync
cd ../web && npm install
```

Then, in two terminals from the repo root:

```bash
make api    # FastAPI on :8000
make web    # Next.js on :3000
```

Open http://localhost:3000, submit a requirement, and approve (or reject)
at each of the three gates as the pipeline pauses.

## Demo tooling

```bash
make preflight     # validates config, DB schema, and LLM provider reachability
make demo-reset    # wipes DB + checkpoint + test_cases.json, recreates schema
make test          # pytest — 35 tests: purity, gate mechanics, reliability, confidence, LLM swap
```

## Switching the LLM adapter

Set `LLM_PROVIDER_ADAPTER=claude` and `ANTHROPIC_API_KEY=...` in `.env` — no
node or router code changes. `control-plane/api/tests/test_llm_provider_swap.py`
smoke-tests exactly this.

## Not built yet

No real agent prompts or reasoning in these nodes, no eval harness, no
adapters beyond one default per interface, no hosting or deployment infra,
no authentication. See the gap register in the architecture notes.
