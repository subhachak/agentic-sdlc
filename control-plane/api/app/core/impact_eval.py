"""Measuring whether the predicted impact set contains what actually changed.

Every number this platform quotes about blast radius has so far been a
property of the code that produces it, not evidence that it works. This is
the missing half: a corpus, a ground truth, and a recall figure that can
regress visibly instead of being re-derived by hand each time someone asks.

The ground truth is co-change. For a commit that touched files {A, B, C},
holding out A and predicting from it should reach B and C — they were edited
together, so something coupled them. That is a proxy and worth naming as one:

  - Files can change together for reasons no dependency graph models: one
    release bump, one lint sweep, one person tidying as they pass.
  - A commit that splits work across unrelated areas inflates the expected
    set and depresses recall for reasons that are not the graph's fault.
  - Coupling the graph gets right may simply not appear in history yet.

So the number is not "impact accuracy" in the abstract. It is: how much of
what developers actually edited together does this graph reach. That is
measurable, it moves when the graph improves, and it is honest about what it
is not.

Reported against baselines, because a recall figure alone means nothing. A
predictor returning the whole repository scores perfect recall; one returning
the seed's own directory is the answer you get without any dependency
analysis at all. The graph has to beat the second to be worth running.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import mean


@dataclass(frozen=True)
class Case:
    """One held-out file and the files it was committed alongside."""

    commit: str
    seed: str
    expected: frozenset[str]

    @property
    def size(self) -> int:
        return len(self.expected)


@dataclass
class Scored:
    case: Case
    predicted: frozenset[str]

    @property
    def hits(self) -> frozenset[str]:
        return self.predicted & self.case.expected

    @property
    def recall(self) -> float:
        return len(self.hits) / len(self.case.expected) if self.case.expected else 1.0

    @property
    def precision(self) -> float:
        return len(self.hits) / len(self.predicted) if self.predicted else 0.0


@dataclass
class Report:
    """Aggregate numbers for one predictor over one corpus."""

    name: str
    scored: list[Scored] = field(default_factory=list)

    @property
    def cases(self) -> int:
        return len(self.scored)

    @property
    def recall(self) -> float:
        """Mean per-case recall.

        Per-case rather than pooled, so one commit touching forty files
        cannot dominate the figure that forty commits touching two files
        contributed to.
        """
        return round(mean([s.recall for s in self.scored]), 4) if self.scored else 0.0

    @property
    def precision(self) -> float:
        return round(mean([s.precision for s in self.scored]), 4) if self.scored else 0.0

    @property
    def mean_radius(self) -> float:
        return round(mean([len(s.predicted) for s in self.scored]), 2) if self.scored else 0.0

    @property
    def perfect(self) -> int:
        """Cases where the radius contained everything that changed with it."""
        return sum(1 for s in self.scored if s.recall == 1.0)

    @property
    def missed_everything(self) -> int:
        return sum(1 for s in self.scored if s.recall == 0.0)

    def as_dict(self) -> dict:
        return {
            "predictor": self.name,
            "cases": self.cases,
            "recall": self.recall,
            "precision": self.precision,
            "mean_radius_files": self.mean_radius,
            "complete_hits": self.perfect,
            "complete_misses": self.missed_everything,
        }


def build_cases(
    commits: dict[str, set[str]],
    *,
    known_files: set[str],
    min_files: int = 2,
    max_files: int = 20,
) -> list[Case]:
    """Turn commit histories into held-out prediction problems.

    Restricted to files the graph currently holds: a commit that touched a
    file since deleted asks the graph about something it has no node for, and
    scoring that as a miss measures history, not prediction.

    Large commits are excluded rather than kept, and the cap is a judgement
    call worth stating: above roughly twenty files a commit is usually a
    rename sweep or a vendored update, where co-change carries no coupling
    signal at all and every predictor looks equally bad.
    """
    cases: list[Case] = []
    for commit, files in sorted(commits.items()):
        present = {f for f in files if f in known_files}
        if not (min_files <= len(present) <= max_files):
            continue
        for seed in sorted(present):
            cases.append(Case(commit, seed, frozenset(present - {seed})))
    return cases


def score(name: str, cases: list[Case], predict) -> Report:
    """Run one predictor over the corpus.

    `predict` takes a seed path and returns the set of files it claims a
    change there could reach, excluding the seed itself.
    """
    report = Report(name)
    for case in cases:
        predicted = frozenset(predict(case.seed)) - {case.seed}
        report.scored.append(Scored(case, predicted))
    return report


def graph_predictor(file_dependents: dict[str, set[str]], depth: int = 1):
    """The real thing: reverse-dependency traversal over the context graph."""

    def predict(seed: str) -> set[str]:
        reached: set[str] = set()
        frontier = {seed}
        for _ in range(max(0, depth)):
            nxt: set[str] = set()
            for path in frontier:
                nxt |= file_dependents.get(path, set())
            frontier = nxt - reached - {seed}
            reached |= frontier
        return reached

    return predict


def directory_predictor(known_files: set[str], depth: int = 4):
    """The answer without any dependency analysis: everything alongside it.

    The baseline the graph has to beat. If reverse-import traversal cannot
    outperform "files in the same directory", the traversal is not earning
    its complexity.
    """
    def module_of(path: str) -> str:
        return "/".join(path.split("/")[:-1][:depth])

    buckets: dict[str, set[str]] = {}
    for path in known_files:
        buckets.setdefault(module_of(path), set()).add(path)

    def predict(seed: str) -> set[str]:
        return set(buckets.get(module_of(seed), set()))

    return predict


def everything_predictor(known_files: set[str]):
    """Perfect recall, useless precision. Present so the recall column has a
    ceiling to read against."""
    def predict(_seed: str) -> set[str]:
        return set(known_files)

    return predict
