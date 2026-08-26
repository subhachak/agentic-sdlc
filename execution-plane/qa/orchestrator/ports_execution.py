"""Ports: how tests get their data, and how they get run.

Neither existed. Test data was `data_store.py` — a module that reads and
writes one JSON file — called directly from the seeding and run nodes, and
execution was `subprocess.run(["npx", "playwright", "test"])` written into a
node. Both are perfectly good defaults and neither was replaceable, so a
client whose fixtures live in Postgres, or whose suite is Cypress or pytest,
had to fork the pipeline.

Two ports rather than one, because they fail differently and a client will
usually replace only one of them. A team can keep the shipped runner and
bring their own data provider, or the reverse.

On isolation. The current provider gives run-level isolation: snapshot the
store, run, restore. That is honest but coarse — mutating specs share a
store, so they run with `--workers=1`, which is the only mechanism available
without changing the application under test. Per-scenario isolation is a
property of the *provider*, not of the pipeline, which is why it is declared
here rather than assumed: a provider backed by a database can lease a
transaction per scenario and roll it back; one backed by a JSON file cannot.
The pipeline reads the declaration and decides how much parallelism it is
allowed, instead of hardcoding one worker forever.

On teardown. Restoration used to be implicit and unverified. A provider now
has to *attest* what it put back, because "we restored it" and "we ran the
restore code" are different claims — and the second one is what a leaked
fixture in a shared environment looks like from the inside.
"""

from __future__ import annotations

from typing import Any, Literal, Protocol

# Bumped when the shape crossing this boundary changes. The QA plane and
# whatever a client plugs in are separately deployed, so a contract neither
# side versions is one that breaks silently in the field.
EXECUTION_CONTRACT_VERSION = 1

# How well a provider can separate one scenario's data from another's.
#   none     — scenarios share everything; only one may mutate at a time
#   run      — the whole run is isolated and restored afterwards
#   scenario — each scenario gets its own, and they may run in parallel
Isolation = Literal["none", "run", "scenario"]


class Lease:
    """One scenario's or one run's claim on test data.

    Carries the handle the provider needs to release it, and whatever the
    tests need in order to find their data — a tenant id, a connection
    string, a seeded row's key. Opaque to the pipeline: it hands `env` to the
    runner and never interprets it.
    """

    def __init__(self, handle: str, env: dict[str, str] | None = None,
                 scope: str = "run", seeded: list[dict[str, Any]] | None = None) -> None:
        self.handle = handle
        self.env = env or {}
        self.scope = scope
        self.seeded = seeded or []


class Attestation:
    """What a provider says it did on the way out.

    `restored` is the claim; `verified` is whether the provider checked
    rather than assumed. A provider that cannot verify says so, and the gate
    treats an unverified teardown as a finding rather than as success —
    silently leaving fixtures in a shared environment is the failure this
    exists to make visible.
    """

    def __init__(self, handle: str, restored: bool, verified: bool,
                 residue: list[str] | None = None, detail: str = "") -> None:
        self.handle = handle
        self.restored = restored
        self.verified = verified
        self.residue = residue or []
        self.detail = detail

    def as_dict(self) -> dict[str, Any]:
        return {
            "handle": self.handle,
            "restored": self.restored,
            "verified": self.verified,
            "residue": self.residue,
            "detail": self.detail,
        }


class TestDataProvider(Protocol):
    """Where a run's data comes from, and where it goes afterwards."""

    contract_version: int
    isolation: Isolation

    def shape(self) -> dict[str, set[str]]: ...
    """Entities and fields a scenario may reference.

    The testability gate reads this. A scenario naming an entity or field
    the provider cannot supply is refused before anyone writes a spec, which
    is the difference between a plan that fails at authoring time and one
    that fails at run time with a missing row."""

    def acquire(self, *, scope: str, scenarios: list[dict[str, Any]]) -> Lease: ...
    """Claim data for a run, or for one scenario when isolation allows it.

    Given the scenarios so a provider can seed exactly what they ask for
    rather than a fixed fixture set — seeding everything is how a suite
    acquires dependencies on rows no test declared."""

    def release(self, lease: Lease) -> Attestation: ...
    """Give it back, and say what actually happened."""


class TestRunner(Protocol):
    """How specs get executed and results come back.

    Playwright is the default and was hardcoded in a node. A client running
    Cypress, pytest or a proprietary harness replaces this; what does not
    move is that results are parsed into the same shape, because the gate
    reasons over outcomes and must not learn a second vocabulary.
    """

    contract_version: int
    name: str

    def supports_parallel(self) -> bool: ...
    """Whether this runner can run specs concurrently at all. Combined with
    the provider's isolation to decide worker count — a parallel runner over
    a run-isolated store is still one worker."""

    def execute(
        self,
        *,
        specs: list[str],
        workers: int,
        env: dict[str, str],
        evidence_dir: str,
    ) -> dict[str, Any]: ...
    """Run them and return the raw result document.

    Raw rather than parsed: parsing belongs to whoever knows the runner's
    format, and a runner that pre-digested its results could hide a failure
    by reporting a shape the gate reads as empty."""


def workers_for(provider_isolation: Isolation, runner_parallel: bool,
                mutating: bool) -> int:
    """How much parallelism this combination actually permits.

    The rule that was `if mutating: --workers=1`, written where the two
    facts it depends on were not available. Now it is one function of both
    declarations, so a provider that gains per-scenario isolation gets
    parallelism without anyone editing the run node.
    """
    if not runner_parallel:
        return 1
    if not mutating:
        return 0  # the runner's own default
    return 0 if provider_isolation == "scenario" else 1
