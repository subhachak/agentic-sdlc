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

# Bumped when the *derivation* changes, which is a different thing from the
# namespace. A graph records the version it was built with, and a mismatch
# means re-index rather than silently mixing two id schemes in one store.
#
#   1  f"{type}|{system}|{external_id}" — unescaped
#   2  escaped, so a value containing the delimiter cannot impersonate
#      another triple
IDENTITY_VERSION = 2

_DELIMITER = "|"
_ESCAPE = "\\"


def _escape(part: str) -> str:
    """Make one component unable to look like two.

    Without this, ("code", "a|b") and ("code|a", "b") join to the same
    string and therefore the same uuid5 — two different things sharing an
    identity. Reachable through any external id the platform does not
    control: a client work-item key, a document id, a path on a filesystem
    that permits the character.

    The backslash is escaped first, or escaping the delimiter would itself
    become ambiguous: "a\\" + "b" and "a" + "\\b" would otherwise collide.
    """
    return part.replace(_ESCAPE, _ESCAPE * 2).replace(_DELIMITER, _ESCAPE + _DELIMITER)


def node_id(node_type: str, system: str, external_id: str) -> str:
    """Stable id for one real-world thing, as seen through one system.

    Stable across revisions on purpose: a file rewritten at a new commit is
    the same file. Which revision a statement was true at belongs on the
    assertion, not on the node — see graph/revision.py.
    """
    parts = _DELIMITER.join(_escape(p) for p in (node_type, system, external_id))
    return str(uuid.uuid5(NAMESPACE, parts))
