"""The set of tests a project admits are broken — and may not add to.

The differential gate stops a red suite from refusing every change, which is
what makes it installable. On its own it also makes a permanent excuse: the
pre-existing list can grow forever and nothing notices, so "attribution"
quietly becomes "tolerance" and the suite rots at exactly the speed nobody
is measuring.

The ratchet is what turns the permissive default into a self-tightening one.
Debt has to be declared, in a file in the repository under test, and the run
compares what is actually failing at base against what was declared:

    declared  failing at base   verdict
    yes       yes               honoured. Pre-existing, does not block.
    no        yes               the debt grew without anyone saying so. Blocks.
    yes       no                stale. Fixed, and the record should shrink.

So you can pay debt down and never add it. A test that starts failing has to
be either fixed or *written down*, and writing it down is a commit somebody
reviews — which is the point. The file is the artefact that makes the
tolerance visible; without it the gate is tolerant in private.

Two things it deliberately does not do.

It does not create the file itself. A pipeline that silently recorded
whatever was failing would ratchet in the wrong direction on its first run
and call it a baseline. It writes a proposal into the evidence directory
instead, so adopting the record is somebody's decision and one commit.

And it does not treat a missing file as an empty one. No record means the
ratchet has no prior to measure growth against, which is "not yet adopted",
not "nothing is allowed to fail" — the second would refuse every change to
the very codebases this exists to make adoptable.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Ratchet:
    established: bool
    honoured: list[str] = field(default_factory=list)
    grew: list[str] = field(default_factory=list)
    stale: list[str] = field(default_factory=list)
    proposal: list[str] = field(default_factory=list)

    @property
    def blocking(self) -> list[str]:
        return sorted(self.grew)

    def as_dict(self) -> dict[str, Any]:
        return {
            "established": self.established,
            "honoured": self.honoured,
            "grew": self.grew,
            "stale": self.stale,
            "proposal": self.proposal,
        }


def load(path: Path) -> set[str] | None:
    """The declared set, or None where a project has not adopted one.

    A malformed file is None as well, and the difference shows up as the run
    reporting that no record was established — a record nobody can read is
    not a record, and guessing at its intent would be worse than saying so.
    """
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
    except (ValueError, OSError):
        return None
    entries = data.get("known_failing") if isinstance(data, dict) else data
    if not isinstance(entries, list):
        return None
    return {str(e) for e in entries if e}


def assess(
    baseline: dict[str, str] | None,
    declared: set[str] | None,
    *,
    strict: bool = False,
) -> Ratchet:
    """Compare what is broken against what was admitted to being broken."""
    failing = sorted(
        script for script, verdict in (baseline or {}).items() if verdict == "failed"
    )

    if strict:
        # No debt is admissible. The position for a team whose suite is green
        # and intends to keep it that way.
        return Ratchet(established=True, grew=failing, proposal=failing)

    if declared is None:
        # Not adopted. Report what a record would contain and measure no
        # growth, because there is no prior to measure against.
        return Ratchet(established=False, honoured=failing, proposal=failing)

    return Ratchet(
        established=True,
        honoured=sorted(set(failing) & declared),
        grew=sorted(set(failing) - declared),
        stale=sorted(declared - set(failing)),
        # What the file should say after this run: the honoured set, minus
        # anything now fixed. Never includes the growth — proposing that
        # would be the pipeline offering to launder a new failure into an
        # accepted one.
        proposal=sorted(set(failing) & declared),
    )
