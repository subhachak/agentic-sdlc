"""What was already broken before this change touched anything.

A regression gate that fails on any failing required script is not testing
for regressions. It is testing for failures, and those are different claims:
a suite red before the change is red because of something else, and blocking
on it means a codebase with any pre-existing failure can never merge
anything. Pointed at a real application this stopped being theoretical
immediately — Fronei's own e2e suite has been failing three of five specs in
its own CI since July, so every run would have been refused for reasons no
change under test could fix.

The same reasoning already governs coverage gaps, which report rather than
block because "refusing every such change would refuse every change to a
codebase that has not finished building a regression suite". It was applied
to coverage and not to regressions, and there is no principle under which
those differ.

So the required set runs twice — once at base, once at head — and the
comparison decides:

    base    head    verdict
    pass    pass    fine
    pass    FAIL    regression. This change broke it. Blocking.
    FAIL    FAIL    pre-existing. Reported, never blocking.
    FAIL    pass    fixed by this change. Worth saying out loud.

The fifth case is the one to get right: no baseline at all. That is not
"probably pre-existing" — it is "nobody looked", and treating unknown as
benign is how a gate stops being one. Without a baseline every failure
blocks, exactly as before, and the run says the baseline was never
established rather than letting the silence imply it passed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Verdict = Literal["passed", "failed", "missing"]


@dataclass
class Differential:
    established: bool
    regressions: list[str] = field(default_factory=list)
    pre_existing: list[str] = field(default_factory=list)
    repaired: list[str] = field(default_factory=list)
    # Failing at head, and the baseline has nothing to say about it — a
    # script that did not exist at base, or one the baseline run never
    # reached. Blocks, because unknown is not the same as excused.
    unexplained: list[str] = field(default_factory=list)

    @property
    def blocking(self) -> list[str]:
        return sorted(self.regressions + self.unexplained)

    def as_dict(self) -> dict[str, Any]:
        return {
            "established": self.established,
            "regressions": self.regressions,
            "pre_existing": self.pre_existing,
            "repaired": self.repaired,
            "unexplained": self.unexplained,
        }


def compare(
    failed_at_head: list[str],
    required: list[str],
    baseline: dict[str, Verdict] | None,
) -> Differential:
    """Which head failures this change is answerable for."""
    if not baseline:
        # Everything that failed blocks, and the caller is told the
        # comparison never happened. Reporting these as pre-existing would
        # turn an unrun baseline into a blanket excuse.
        return Differential(established=False, unexplained=sorted(failed_at_head))

    failed = set(failed_at_head)
    out = Differential(established=True)

    for script in sorted(failed):
        verdict = baseline.get(script)
        if verdict == "failed":
            out.pre_existing.append(script)
        elif verdict == "passed":
            out.regressions.append(script)
        else:
            # Absent or "missing": the baseline run did not produce a result
            # for this script. Blocks — the alternative is that a script
            # which fails to run at base grants itself an exemption at head.
            out.unexplained.append(script)

    # Worth reporting even though nothing turns on it: a change that fixes a
    # long-broken regression should be able to say so, and the manifest's
    # notion of what passes is corrected by observing that it now does.
    out.repaired = sorted(
        script
        for script in required
        if baseline.get(script) == "failed" and script not in failed
    )
    return out
