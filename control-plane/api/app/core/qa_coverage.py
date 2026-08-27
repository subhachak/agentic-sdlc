"""Reconcile what QA was obliged to cover against what it says it covered.

The platform hands a provider the blast radius and lets it test however it
likes. This is the half that does not move: whatever it decided, it has to
account for the difference, and ordinary code — not the provider, and not a
model — compares the two.

Three outcomes, kept apart because they are different facts and collapsing
them is how "we did not check" comes to read like "there was nothing to
check":

  covered      obliged, and the provider says it exercised it
  unaccounted  obliged, and the provider's own report does not mention it
  volunteered  not obliged, exercised anyway — never a problem, but worth
               recording, because it is how a manifest's declared coverage
               gets corrected by observation

`evaluated` is the fourth answer and the important one. A provider whose
capabilities say it cannot report coverage produces no accounting, and an
empty accounting must not be read as "covered nothing" — that would fail
every run from a provider that is merely quiet, and the fix teams would
reach for is to stop asking.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CoverageReconciliation:
    evaluated: bool
    covered: list[str] = field(default_factory=list)
    unaccounted: list[str] = field(default_factory=list)
    volunteered: list[str] = field(default_factory=list)
    # What the provider itself flagged as out of reach. Distinct from
    # `unaccounted`: one is a provider saying "I could not cover this", the
    # other is a provider not saying anything. The first is a disclosure and
    # the second is a gap in the report.
    declared_uncovered: list[str] = field(default_factory=list)
    detail: str = ""

    @property
    def complete(self) -> bool:
        """Every obligation accounted for — covered or explicitly declined.

        False when the coverage half was not evaluated at all: a run nobody
        checked has not demonstrated completeness, and reporting it as
        complete is the specific lie this module exists to prevent.
        """
        return self.evaluated and not self.unaccounted

    def as_dict(self) -> dict[str, Any]:
        return {
            "evaluated": self.evaluated,
            "complete": self.complete,
            "covered": self.covered,
            "unaccounted": self.unaccounted,
            "volunteered": self.volunteered,
            "declared_uncovered": self.declared_uncovered,
            "detail": self.detail,
        }


def reconcile(
    required: list[str],
    covered: list[str],
    declared_uncovered: list[str] | None = None,
    *,
    reports_coverage: bool = True,
) -> CoverageReconciliation:
    obliged = {m for m in required if m}
    claimed = {m for m in covered if m}
    declined = {m for m in (declared_uncovered or []) if m}

    if not reports_coverage:
        return CoverageReconciliation(
            evaluated=False,
            detail=(
                "the QA provider does not report coverage, so what it exercised "
                "could not be checked against the blast radius"
            ),
        )

    # A provider that says it could not cover something has accounted for it.
    # The claim is now visible and the release decision can weigh it; that is
    # a different situation from the module going unmentioned.
    unaccounted = obliged - claimed - declined

    return CoverageReconciliation(
        evaluated=True,
        covered=sorted(obliged & claimed),
        unaccounted=sorted(unaccounted),
        volunteered=sorted(claimed - obliged),
        declared_uncovered=sorted(obliged & declined),
        detail=(
            f"{len(obliged & claimed)}/{len(obliged)} obliged module(s) covered"
            + (f", {len(unaccounted)} unaccounted" if unaccounted else "")
            + (f", {len(obliged & declined)} declared uncovered" if obliged & declined else "")
        ),
    )
