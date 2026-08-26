"""The shipped TestDataProvider: one JSON file, restored after the run.

Declares `run` isolation rather than claiming more. The store is a single
file the application reads, so two scenarios mutating it are visible to each
other and nothing here can give them a private copy without changing the
application under test. Saying so is what lets the pipeline decide worker
count from a fact instead of a hardcoded `--workers=1`.

Teardown is verified rather than assumed: the restore is read back and
compared. "We ran the restore code" and "the store is as it was" are
different claims, and only the second is evidence.
"""

from __future__ import annotations

from typing import Any

from orchestrator import data_store
from orchestrator.paths import DATA_STORE
from orchestrator.ports_execution import (
    EXECUTION_CONTRACT_VERSION,
    Attestation,
    Lease,
)


class JsonFileTestData:
    contract_version = EXECUTION_CONTRACT_VERSION
    isolation = "run"

    def __init__(self) -> None:
        self._taken: dict[str, str | None] = {}

    def shape(self) -> dict[str, set[str]]:
        return data_store.shape()

    def acquire(self, *, scope: str, scenarios: list[dict[str, Any]]) -> Lease:
        handle = f"json:{scope}"
        # None is not the same as an empty store, and has to be restored
        # differently — putting an empty file back where there was no file
        # leaves a git-tracked artefact behind.
        self._taken[handle] = data_store.snapshot()
        return Lease(handle=handle, scope=scope)

    def release(self, lease: Lease) -> Attestation:
        if lease.handle not in self._taken:
            return Attestation(
                lease.handle, restored=False, verified=True,
                detail="nothing was acquired under this handle",
            )
        original = self._taken.pop(lease.handle)
        changed = data_store.restore(original)

        # Read back. A restore that silently failed looks identical to one
        # that was not needed, and the difference is a dirty store in
        # someone's working copy or a leaked fixture in a shared one.
        current = DATA_STORE.read_text() if DATA_STORE.exists() else None
        verified = current == original
        residue = [] if verified else [str(DATA_STORE)]
        return Attestation(
            lease.handle,
            restored=verified,
            verified=True,
            residue=residue,
            detail=("store restored" if verified else "store did not return to its prior state")
            + ("" if changed else "; nothing had changed"),
        )
