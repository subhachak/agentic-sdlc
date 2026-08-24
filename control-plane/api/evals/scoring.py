"""Deterministic scoring for agent output.

An eval that asks a model whether the output was good inherits the problem it
is meant to measure. Everything here is a property that can be checked without
judgment: did the gate accept, which modules were named, was the file we know
must change actually changed.

What this cannot score is whether the code is *good*. It can score whether it
is admissible, contained, and stable — which is what governs whether the
pipeline is trustworthy, and is the part that regresses silently.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations
from statistics import mean


@dataclass
class Outcome:
    """One run of one phase."""

    accepted: bool
    blocked: str = ""
    modules: list[str] = field(default_factory=list)
    files: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    error: str = ""

    @property
    def usable(self) -> bool:
        return self.accepted and not self.blocked and not self.error


def jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)


def stability(runs: list[Outcome], attr: str = "files") -> float:
    """Mean pairwise agreement between runs of the same input.

    A phase that names a different half of the codebase each time is not
    dependable even when every individual answer is admissible, and nothing
    else in the suite would notice.
    """
    sets = [set(getattr(r, attr)) for r in runs if r.usable]
    if len(sets) < 2:
        return 1.0 if sets else 0.0
    return mean(jaccard(a, b) for a, b in combinations(sets, 2))


def check_expectations(outcome: Outcome, expects: dict) -> list[str]:
    """Return the expectations this run failed."""
    failures: list[str] = []

    if expects.get("accepted") is not None and outcome.accepted != expects["accepted"]:
        failures.append(f"expected accepted={expects['accepted']}, got {outcome.accepted}")

    if expects.get("blocked") is True and not outcome.blocked:
        failures.append("expected the agent to decline, it proposed a change")
    if expects.get("blocked") is False and outcome.blocked:
        failures.append(f"agent declined: {outcome.blocked[:80]}")

    for field_name, key in (("files", "must_touch"), ("modules", "must_name")):
        for wanted in expects.get(key, []) or []:
            values = getattr(outcome, field_name)
            if not any(wanted in v for v in values):
                failures.append(f"{key}: nothing matching {wanted!r} in {field_name}")

    for field_name, key in (("files", "must_not_touch"), ("modules", "must_not_name")):
        for banned in expects.get(key, []) or []:
            values = getattr(outcome, field_name)
            if any(banned in v for v in values):
                failures.append(f"{key}: {banned!r} appears in {field_name}")

    limit = expects.get("max_files")
    if limit is not None and len(outcome.files) > limit:
        failures.append(f"touched {len(outcome.files)} files, expected at most {limit}")

    return failures


@dataclass
class CaseResult:
    case: str
    phase: str
    runs: list[Outcome]
    failures: list[list[str]]
    # A case that expects the agent to decline should not drag the accept rate
    # down: refusing is the correct answer there, and averaging it in reports a
    # worse system than the one being measured.
    expects_decline: bool = False

    @property
    def repeats(self) -> int:
        return len(self.runs)

    @property
    def accept_rate(self) -> float:
        return sum(1 for r in self.runs if r.usable) / self.repeats if self.repeats else 0.0

    @property
    def expectation_rate(self) -> float:
        met = sum(1 for f in self.failures if not f)
        return met / self.repeats if self.repeats else 0.0

    @property
    def file_stability(self) -> float:
        return stability(self.runs, "files")

    @property
    def module_stability(self) -> float:
        return stability(self.runs, "modules")

    @property
    def decline_rate(self) -> float:
        return sum(1 for r in self.runs if r.blocked) / self.repeats if self.repeats else 0.0

    def summary(self) -> dict:
        return {
            "case": self.case,
            "phase": self.phase,
            "repeats": self.repeats,
            "expects_decline": self.expects_decline,
            "accept_rate": round(self.accept_rate, 2),
            "decline_rate": round(self.decline_rate, 2),
            "expectation_rate": round(self.expectation_rate, 2),
            "file_stability": round(self.file_stability, 2),
            "module_stability": round(self.module_stability, 2),
            "failures": [f for f in self.failures if f],
        }
