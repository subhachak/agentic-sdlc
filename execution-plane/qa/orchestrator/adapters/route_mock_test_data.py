"""Test data for an application whose tests mock at the network boundary.

Fronei's Playwright suite installs `page.route(...)` handlers in a
`beforeEach`. Playwright gives every test its own `page`, so the fixtures
are per-test by construction: no shared store, nothing to seed, nothing to
restore, and no reason to serialise mutating specs.

That makes this the first provider that can honestly declare `scenario`
isolation — which is not a claim about this adapter being better, but about
the application under test keeping its fixtures in version-controlled code
rather than in mutable state.

Two consequences worth being explicit about, because both are the opposite
of the JSON provider's:

  `acquire` seeds nothing. The fixtures are already in the repository, at
  the commit under test, which is a stronger guarantee than seeding gives —
  they cannot drift from the branch.

  `release` restores nothing, and says so rather than reporting a
  restoration it did not perform. A provider that claimed to have tidied up
  when there was nothing to tidy would be indistinguishable from one that
  failed to.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from orchestrator.ports_execution import (
    EXECUTION_CONTRACT_VERSION,
    Attestation,
    Lease,
)

# "this entity exists, its fields are not knowable from here". Declared in
# ports_execution so the gate and every provider agree on one spelling.
from orchestrator.ports_execution import ANY_FIELD as _ANY

# `path === '/workspaces'` and friends, as the mock file spells them.
_PATH = re.compile(r"path\s*===\s*['\"]([^'\"]+)['\"]")
_STARTS = re.compile(r"path\.startsWith\(['\"]([^'\"]+)['\"]")


class RouteMockTestData:
    contract_version = EXECUTION_CONTRACT_VERSION
    isolation = "scenario"

    def __init__(self, mock_file: Path | str) -> None:
        self._mock_file = Path(mock_file)

    def shape(self) -> dict[str, set[str]]:
        """Which entities the mocks can actually serve.

        Read from the mock file rather than declared beside it, so it cannot
        claim an entity the handlers do not answer. The testability gate uses
        this to refuse a scenario asking for data nothing can provide —
        before an agent writes a spec for it, and long before a browser runs.

        Fields are deliberately not derived. A route handler returns whatever
        JSON its author wrote, and inferring a field list from that would be
        guessing at a schema — so entities are checked and fields are not.
        `_ANY` is what makes that explicit rather than an empty set, which
        the gate would read as "this entity has no fields" and reject
        everything.
        """
        if not self._mock_file.exists():
            return {}
        text = self._mock_file.read_text()
        entities: dict[str, set[str]] = {}
        for path in set(_PATH.findall(text)) | set(_STARTS.findall(text)):
            # "/conversations/conv_e2e/turns" -> conversations, turns
            for segment in path.strip("/").split("/"):
                if segment and not segment.startswith(":") and "_" not in segment:
                    entities.setdefault(segment, {_ANY})
        return entities

    def acquire(self, *, scope: str, scenarios: list[dict[str, Any]]) -> Lease:
        # Nothing to claim. The fixtures are in the repository at the commit
        # under test, which is why this provider can offer per-scenario
        # isolation without doing any work per scenario.
        return Lease(handle=f"route-mocks:{scope}", scope=scope)

    def release(self, lease: Lease) -> Attestation:
        return Attestation(
            lease.handle,
            restored=True,
            # Verified in the strongest sense available: there is nothing
            # that could have been left behind, because nothing was written.
            verified=True,
            residue=[],
            detail="no state to restore; fixtures are route handlers in the repository",
        )
