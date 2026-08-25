"""The application's data store, as the pipeline sees it.

Shared by the testability gate, which needs to know what a scenario is
allowed to ask for, and the seeding node, which has to provide it. Keeping
the shape in one place is what stops the two disagreeing about what data can
exist — which is exactly how a plan gets accepted and then fails at run time
because nothing created the row it assumed.
"""

from __future__ import annotations

import json
import re
from typing import Any

from orchestrator.paths import DATA_STORE

_ID_PATTERN = re.compile(r"^(?P<prefix>.*?)(?P<number>\d+)$")


def load() -> dict[str, Any]:
    return json.loads(DATA_STORE.read_text())


def save(store: dict[str, Any]) -> None:
    DATA_STORE.write_text(json.dumps(store, indent=2) + "\n")


def snapshot() -> str | None:
    """The store as it was before this run touched it.

    Seeding is additive and there was no teardown at all: the store was
    written and left. That was survivable only because both real execution
    paths throw the whole checkout away afterwards — a worktree that gets
    removed, or a fresh CI clone. Neither is true of a developer running the
    pipeline against their working copy, where seeding permanently modified a
    git-tracked file.

    `None` means the store did not exist, which is a different state from an
    empty one and has to be restored differently.
    """
    return DATA_STORE.read_text() if DATA_STORE.exists() else None


def restore(original: str | None) -> bool:
    """Put the store back. Returns whether anything had to change.

    Called unconditionally at the end of a run rather than only when seeding
    happened, because a test that writes through the application would leave
    the store dirty too and nothing else would notice.

    A store that did not exist before is deleted rather than left: an adapter
    whose provider creates its store during setup would otherwise leave the
    file behind, and the next run would seed on top of it believing it was
    the application's own data.
    """
    if original is None:
        if DATA_STORE.exists():
            DATA_STORE.unlink()
            return True
        return False

    if DATA_STORE.exists() and DATA_STORE.read_text() == original:
        return False
    DATA_STORE.parent.mkdir(parents=True, exist_ok=True)
    DATA_STORE.write_text(original)
    return True


def shape(store: dict[str, Any] | None = None) -> dict[str, set[str]]:
    """Entity name to the fields its rows carry.

    Derived from the data rather than declared, so it cannot drift from what
    the application actually serves.
    """
    store = store if store is not None else load()
    out: dict[str, set[str]] = {}
    for entity, rows in store.items():
        if isinstance(rows, list) and rows and isinstance(rows[0], dict):
            out[entity] = set(rows[0])
    return out


def next_id(rows: list[dict[str, Any]], entity: str) -> str:
    """Continue whatever id scheme the existing rows use."""
    numbers = []
    prefix = f"{entity[:3].upper()}-"
    for row in rows:
        match = _ID_PATTERN.match(str(row.get("id", "")))
        if match:
            numbers.append(int(match.group("number")))
            prefix = match.group("prefix")
    return f"{prefix}{max(numbers) + 1 if numbers else 1}"


def make_row(rows: list[dict[str, Any]], entity: str, field: str, value: str) -> dict[str, Any]:
    """A fixture shaped like the rows already there, with one field pinned.

    Templated on a real row rather than invented, so a new field added to the
    application does not silently produce fixtures that are missing it.
    """
    template = dict(rows[0]) if rows else {"id": "", field: value}
    row = {key: template[key] for key in template}
    row["id"] = next_id(rows, entity)
    row[field] = value
    for key in row:
        if key not in ("id", field) and isinstance(row[key], str):
            row[key] = "Seeded Fixture" if key.lower().endswith("holder") else row[key]
    return row
