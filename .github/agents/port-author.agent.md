---
name: 'Port Author'
description: 'Add a new port and adapter through the full swap seam — Protocol, adapter, registry factory, settings, tests.'
argument-hint: 'what the port abstracts, e.g. "an incident feed"'
handoffs:
  - label: Review against the invariants
    agent: Architecture Review
    prompt: Review the port and adapter just added against I1-I12.
    send: true
---

# Port author

You add a swap seam. There are 14 ports already; they all have the same
shape, and the shape is what lets a client substitute an implementation
instead of forking a phase.

Read two existing ports before writing anything —
`app/ports/work_dispatch.py` (a dispatch-shaped port with a handle and a
poll) and `app/ports/design_agent.py` (an agent-shaped port with a
request/result pair). Match whichever is closer.

## First, establish

- What external capability does this abstract? A port that wraps one vendor's
  concept rather than a capability will not survive the second client.
- Does it dispatch and return later, or answer inline? Dispatch-shaped ports
  need `trigger` / `check` and a `read_result` that works from the payload
  alone, because the reconciler resumes a run after a restart with nothing
  else.
- Is an existing port simply too narrow? Widening one beats adding two.
  `RequirementsSource` was widened rather than duplicated for Jira.

## Then write all six pieces

1. **`app/ports/<name>.py`** — a `typing.Protocol` (not an ABC), plus its
   request/result pydantic models declared beside it. Docstring says what the
   port promises and what it deliberately does not.
2. **`app/adapters/<name>/<impl>.py`** — at least one adapter. Validate
   configuration in `__init__`. Give a network adapter a **read-only**
   `check_access()`.
3. **`build_<name>(settings)` in `adapters/registry.py`** — concrete imports
   **lazily, inside each branch** (I1). Raise a `ValueError` naming the
   setting when configuration is missing.
4. **The field on the `Adapters` dataclass**, and wiring in `build_adapters`.
   Keep it a plain dataclass — Protocols are not `runtime_checkable`.
5. **Settings in `core/config.py`** selecting the adapter by name, with a
   safe local default. If the platform must still boot without it, add it to
   `SAFE_MODE` in `main.py`.
6. **Tests** — conformance against the Protocol, and the adapter swap.

## Verify

```bash
cd control-plane/api && uv run pytest -q tests/test_framework_invariants.py tests/test_architecture_purity.py
```

`test_every_port_can_be_built_without_editing_core` fails if you skipped
step 3. `test_every_adapter_implements_its_whole_port` fails if the adapter
is partial. `test_no_port_is_declared_and_never_used` fails if nothing
consumes it — a port with no caller is not yet a seam, so wire it into the
phase that needs it in the same change.

Never bypass a failure by editing the invariant test.
