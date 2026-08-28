---
name: 'Tests'
description: 'Testing conventions — the invariants are themselves tests.'
applyTo: '**/tests/**,**/test_*.py,**/conftest.py'
---

# Tests

In this repo the architecture is enforced by tests, not by convention. Three
files are load-bearing and should be read before changing structure:

- `tests/test_architecture_purity.py` — no control-plane module reaches
  `anthropic`. Each check runs in a **clean subprocess**, because a module
  already imported by another test would produce a false negative.
- `tests/test_framework_invariants.py` — every port has a factory, no port is
  unused, core imports no concrete adapter, every edge type declares an impact
  stance, a fresh clone builds with no credentials.
- `tests/test_context_graph.py::test_both_planes_derive_the_same_node_id` —
  the two copies of `identity.py` agree.

## Conventions

- Use the existing doubles rather than inventing new ones:
  `tests/dispatch_doubles.py`, `graph_doubles.py`, `implementation_doubles.py`.
  A double must return the shape production returns — there is a commit whose
  whole subject is a graph double that did not.
- **No test may build `Settings` from the developer's own environment.**
  There is a test asserting this. Construct settings explicitly.
- New behaviour ships with its test in the same commit. When you change an
  invariant, change its test deliberately and explain why in the message —
  never route around it.
- Prefer asserting the *reason* a decision was made, not only the verdict.
  Much of this codebase returns `reasons` / `notes` lists precisely so a test
  can pin the argument rather than the boolean.

## Running

```bash
cd control-plane/api   && uv run pytest -q                      # 727 passed, 4 skipped
cd execution-plane/qa  && .venv/bin/python -m pytest tests/ -q  # 277 passed
```

`make test` runs both. `make test-qa` creates the execution plane's venv on
first use; the explicit form above skips that check.
