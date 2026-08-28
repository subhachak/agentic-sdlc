---
name: 'Phase Node'
description: 'Add or change a pipeline node in either plane, preserving gate determinism and the audit trail.'
argument-hint: 'the phase, e.g. "a security-scan node after implementation"'
handoffs:
  - label: Review against the invariants
    agent: Architecture Review
    prompt: Review the node just added or changed against I1-I12, especially I2, I3 and the routing rules.
    send: true
---

# Phase node

Establish which plane first — the answer changes everything below.

## Control plane (`control-plane/api/app/agents/`)

Nodes are closures built inside `build_nodes()`, wrapped by
`business(name, fallback)` (retry + audit), returning a **partial state
dict**.

1. Write the node inside `build_nodes()`. It may reference only `ports/`
   Protocol types and `core/` (I4).
2. Register it in the returned dict at the bottom of `build_nodes()`.
3. Add the edge in `agents/graph.py`. If it can reject, use a conditional
   edge that routes to `END` — and **route on `state["status"]`, not on
   whether some field is truthy.** The earlier truthiness test let refused
   changes reach QA; only QA having nothing to test stopped them.
4. If the node pauses — for a human or for a remote job — call
   `gate_controller.request_gate` or `request_external`. **Never call
   `interrupt()` yourself** (I3). Remember the node re-runs from its top on
   resume: guard audit writes with `has_written`, and guard the actual
   dispatch with `dispatch_store.claim`, which returns `None` when a row
   already exists.
5. **Do not wrap a gate or a parking node in `business()`.** A fallback there
   would manufacture a verdict no work produced.
6. New state fields go on `PipelineState`. A new pydantic model must also be
   added to the serde allowlist in `main.py`, or paused runs stop resuming.
7. If the node writes to the context graph, scope every system name with
   `scoped(system, project)` and take `project` from the state (I9, and see
   the release-phase bug where unscoped nodes landed in the wrong project).

## Execution plane (`execution-plane/qa/orchestrator/`)

Nodes are plain functions `run(state: PipelineState) -> PipelineState`
returning `{**state, ...}`, registered in `graph.py`.

1. Add the module under `nodes/`, the node and edge in `graph.py`, and the
   fields it writes to `state.py` with a comment saying what they mean.
2. **If it decides anything, it contains no LLM call** (I2). An agent may
   propose; deterministic code accepts. If a proposal can be rejected, feed
   the reasons back for a bounded number of attempts rather than halting.
3. If it executes or writes generated code, it belongs in the `qa-run` job —
   which holds no write token. Reporting belongs after the graph (I10).
4. Report what you could not do rather than omitting it. This codebase
   consistently returns `reasons` / `notes` / `blind_spots` lists so silence
   is never mistaken for success.

## Both planes

A node ships with its test in the same commit. Prefer asserting the reason
alongside the verdict.

```bash
cd control-plane/api && uv run pytest -q
cd execution-plane/qa && .venv/bin/python -m pytest tests/ -q
```
