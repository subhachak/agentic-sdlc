"""Deterministic node identity, shared by both planes.

A node's id is derived from what it *is* — type, source system, native
identifier — rather than allocated. That means the execution plane can emit
assertions about a criterion without asking the control plane what to call
it, and both arrive at the same id. It also makes assertion ingestion
idempotent for free: re-ingesting the same edge cannot create a duplicate
node.

This module is intentionally stdlib-only and is duplicated verbatim at
control-plane/api/app/graph/identity.py. A test asserts the two agree; if
they ever diverge, every cross-plane edge silently points at nothing.
"""

from __future__ import annotations

import uuid

# Frozen. Changing it re-identifies every node ever written.
NAMESPACE = uuid.UUID("6f2a1c7e-9b3d-4a52-8f61-0c4d7e5a2b19")


def node_id(node_type: str, system: str, external_id: str) -> str:
    """Stable id for one real-world thing, as seen through one system."""
    return str(uuid.uuid5(NAMESPACE, f"{node_type}|{system}|{external_id}"))
