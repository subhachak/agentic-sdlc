---
name: 'Ports and adapters'
description: 'The swap seam — adding or changing a port, an adapter, or a registry factory.'
applyTo: 'control-plane/api/app/ports/**,control-plane/api/app/adapters/**'
---

# Ports and adapters

A client substitutes an adapter here rather than forking a phase. Every rule
below protects that.

## Ports

- A port is a `typing.Protocol`, one per file in `app/ports/`. Not an ABC.
- Because Protocols are not `runtime_checkable`, the `Adapters` container in
  `registry.py` is a plain `@dataclass` — pydantic cannot build an
  `isinstance` validator for them. Do not "upgrade" it to a BaseModel.
- Request/result shapes are pydantic models declared **beside the port**
  (`DesignRequest`, `QARequest`, `ImplementationResult`, …). A port that
  takes three loose dict keys is a port that will be widened by guesswork.
- Every declared port must be used, and every adapter must implement its
  **whole** port. Both are enforced by `tests/test_framework_invariants.py`.

## Adapters

- **Import the concrete class lazily, inside its own factory branch.** A
  top-level `import anthropic` (or any transitive path to it) breaks I1 and
  `test_architecture_purity.py` will fail. This is the single most common way
  to break the build here.
- Validate at construction, not at first use. A misconfigured adapter should
  raise a `ValueError` an operator can read — `"llm_provider_adapter=claude
  needs ANTHROPIC_API_KEY"` — rather than failing deep inside a run after the
  gates have been approved. Use `_require_directory` for local adapters.
- Give network adapters a **read-only** `check_access()`. A connection test
  that costs a real agent run and opens a real pull request is not a
  connection test — see `github_copilot.py`, which lists tasks rather than
  starting one.
- Distinguish "still running" from "waiting for a human" in a
  `DispatchResult.detail`. They call for different responses from whoever is
  watching.

## The registry

Adding a port means adding all of:

1. `app/ports/<name>.py` — the Protocol plus its request/result models.
2. `app/adapters/<name>/<impl>.py` — at least one adapter.
3. A `build_<name>(settings)` factory in `registry.py`, with lazy imports.
4. The field on the `Adapters` dataclass, and wiring in `build_adapters`.
5. Settings in `core/config.py` selecting the adapter by name.
6. Tests: conformance against the Protocol, plus the swap.

Skipping (3) is the failure `test_every_port_can_be_built_without_editing_core`
exists to catch: the graph store was once a Protocol like any other but was
constructed directly in `main.py`, so a client wanting Postgres had to edit
the platform's entry point.

## Extending impact semantics

An adapter may contribute traversal behaviour via `impact.register(...)` at
build time — that is how a client's `x_depends_on_policy` edge becomes
something the engine can walk. Overriding a built-in requires `replace=True`
and makes this deployment's numbers incomparable with every other one. Do not
pass it casually.
