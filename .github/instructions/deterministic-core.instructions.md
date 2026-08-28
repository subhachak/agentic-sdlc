---
name: 'Deterministic core'
description: 'Rules for the control plane core and pipeline nodes — the code that decides.'
applyTo: 'control-plane/api/app/core/**,control-plane/api/app/agents/**,control-plane/api/app/routers/**'
---

# You are in the deterministic core

This is the half of the platform that **decides**. It governs state
transitions and gating; agents reason only at the edges. See `AGENTS.md`
I1–I5 — those are hard constraints here, not style.

## Node anatomy

Business nodes are built inside `build_nodes()` and wrapped by the local
`business(name, fallback)` decorator, which composes `with_retry_fallback`
and `audited`. A node returns a **partial state dict**, never mutates.

Three kinds of node are deliberately **not** wrapped in `business()`:

- gate nodes (`gate_1`, `gate_2`, `gate_3`) — they write their own audit
  entries, because a gate's "after" entry carries a `human_decision` the
  generic wrapper cannot know.
- `qa_execution` — a parked node is not a transient failure. Falling back
  would report a QA verdict no test produced. Retries belong inside the
  adapter's HTTP calls.

Preserve that. Wrapping a gate in the retry decorator would let a rejected
gate be retried into an approval.

## State

`PipelineState` is a `total=False` TypedDict in `agents/state.py`.

- **Carry `project` on the state**, never resolve it from whatever is active
  when a phase happens to run. A phase that resolves the project late writes
  its assertions into whichever project someone had switched to. Every graph
  writer must scope with `scoped(system, project)`.
- `confidence_entries` is `Annotated[list[...], operator.add]` — it
  accumulates. Plain fields replace.
- **If you add a pydantic model to the state, register it** in the
  `JsonPlusSerializer(allowed_msgpack_modules=[...])` list in `main.py`.
  The checkpointer will otherwise warn now and refuse later to deserialize
  it, and paused runs will not resume.

## Routing

Conditional edges in `agents/graph.py` must route on **the phase's own
verdict**, not on whether a field is truthy. `_after_implementation` checks
`state["status"] != "awaiting_qa_execution"` precisely because the earlier
truthiness test let refused changes through to QA — the only thing that
stopped them was QA having nothing to test. A rejection must reach `END`.

## Writing to the context graph

Assertions are written by the phase whose gate decided, at the moment it
decides — not by a separate ingestion job. Use `NodeSpec` / `Assertion`, and
scope the system name by project. Record provenance: a prediction (design)
and a measurement (QA) must not be indistinguishable to a later reader.

## Adding configuration

Settings live in `core/config.py` and are layered
base → stored overrides → active project in `main.py:reload_runtime`. The
registry is a pure function of settings, so "apply this change" is just
rebuilding it — do not add a restart requirement. Never read a variable the
CI runner owns (there is a test for this); never accept or read back a secret
through the API.
