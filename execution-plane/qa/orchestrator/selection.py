"""Which regression scripts this change actually obliges — and when to stop
being clever and run everything.

Selection used to be a set intersection: any script whose declared
`covers_modules` met the impacted set. On a real application that returned
the entire library for every change, because a two-script suite declares
broad shared modules and almost any edit touches one. Intersection is not a
decision; it is arithmetic that happens to produce a list.

Three things make it a decision.

Files, not modules. The impact engine is precise per file and carries a
confidence and a test obligation for each — then selection rolled that up to
modules and threw the precision away. Measured across eight real Fronei
commits, matching at file level halves the work on three of them and never
selects more.

Obligation, not reach. A relationship can propagate impact without obliging
a scenario, so the input is `test_obligations` rather than `affected`.
Demanding a regression run for a deployment edge is how a required set
becomes something teams learn to ignore.

And evidence, not assertion, for the part that matters. Including a script
on a declared claim is safe: the worst case is running something that turns
out not to have been needed. *Excluding* one on a declared claim is a bet
that the declaration is complete, and an incomplete declaration means a
regression nobody ran the test for. So a script is skipped only where its
coverage was actually observed at runtime; a script with nothing but a
hand-written claim is kept, and the run says it was kept for want of
evidence rather than because it was needed.

That makes frugality something the pipeline earns. A library with no
observed coverage runs in full and produces the observations; the run after
it is cheap. It is the same ladder as declared -> runtime-observed coverage,
applied to what gets executed rather than to what gets believed.

Escalation is the other half. Being frugal is only safe while the scope can
be trusted, so the conditions that make scope untrustworthy — no assessment,
a graph that describes another commit, an index that resolved too little,
changed files the graph has never heard of — select the whole library and
name the reason. Frugal by default, comprehensive when the evidence for
being frugal is missing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Strategy = Literal["targeted", "full", "none"]

# Below this share of internal imports resolved, the graph does not know the
# codebase well enough for an exclusion to mean anything. Same threshold the
# design gate refuses containment on, for the same reason.
MIN_CAPTURE_RATE = 0.80


@dataclass
class Selection:
    scripts: list[str]
    strategy: Strategy
    reasons: list[str] = field(default_factory=list)
    # Scripts deliberately not run, each with why. Reported because a
    # regression suite that quietly shrank is indistinguishable from one that
    # was quietly disabled.
    skipped: list[dict[str, str]] = field(default_factory=list)
    obliged_files: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "scripts": self.scripts,
            "strategy": self.strategy,
            "reasons": self.reasons,
            "skipped": self.skipped,
            "obliged_files": self.obliged_files,
        }


def _normalise(path: str) -> str:
    return path.strip().lstrip("/").removeprefix("./")


def obliged_files(impact: dict[str, Any] | None) -> set[str]:
    """The files a change obliges a test for, from the assessment.

    Changed files count whether or not a path reached them: an edit is its
    own strongest reason to re-test whatever covers it.
    """
    if not impact:
        return set()
    out = {_normalise(p) for p in impact.get("changed") or []}
    out |= {_normalise(p) for p in impact.get("test_obligations") or []}
    return out


def _escalations(
    impact: dict[str, Any] | None, provenance: dict[str, Any], head_sha: str
) -> list[str]:
    """Reasons to stop narrowing and run the whole library."""
    reasons: list[str] = []

    if not (impact or {}).get("affected"):
        reasons.append(
            "no impact assessment was supplied, so nothing can be excluded on evidence"
        )
        return reasons

    if not provenance.get("generated"):
        reasons.append(
            "the code graph was not generated from an index, so an exclusion would "
            "rest on a hand-maintained file"
        )
    commit = provenance.get("commit_sha")
    if head_sha and commit and commit != head_sha:
        reasons.append(
            f"the code graph describes {commit[:7]}, not the {head_sha[:7]} under "
            f"test — a stale graph can miss the edge that mattered"
        )
    capture = provenance.get("internal_capture_rate")
    if capture is not None and capture < MIN_CAPTURE_RATE:
        reasons.append(
            f"the index resolved only {capture:.1%} of internal imports, below the "
            f"{MIN_CAPTURE_RATE:.0%} an exclusion needs"
        )
    if (impact or {}).get("unmapped"):
        reasons.append(
            "the change touches files the graph does not know: "
            + ", ".join((impact or {})["unmapped"][:5])
        )
    return reasons


def select(
    manifest: list[dict[str, Any]],
    impact: dict[str, Any] | None,
    *,
    provenance: dict[str, Any] | None = None,
    head_sha: str = "",
    observed: dict[str, set[str]] | None = None,
    touches_indexed_scope: bool = True,
) -> Selection:
    """Which scripts to run, and the argument for running exactly those.

    `observed` maps a script id to the files a previous run watched it touch.
    It is what licenses an exclusion; without it a script is kept.

    `touches_indexed_scope` is the caller saying whether the change reaches
    the part of the repository the library tests at all.
    """
    library = [entry for entry in manifest if entry.get("id")]
    if not library:
        return Selection(scripts=[], strategy="none", reasons=["the library is empty"])

    # A change with no bearing on the tested scope runs nothing, and this
    # comes before escalation. It did not, and the result was that editing a
    # README escalated to the entire regression library: with no assessment
    # to narrow with, "cannot be trusted to exclude" fired on a change there
    # was nothing to exclude *from*. Escalation is for a change that has
    # something to test and no reliable way to scope it — not for one that
    # touches nothing.
    if not touches_indexed_scope and not obliged_files(impact):
        return Selection(
            scripts=[],
            strategy="none",
            reasons=["the change touches nothing the regression library covers"],
        )

    escalate = _escalations(impact, provenance or {}, head_sha)
    if escalate:
        return Selection(
            scripts=sorted(entry["id"] for entry in library),
            strategy="full",
            reasons=escalate,
        )

    wanted = obliged_files(impact)
    # Where a manifest entry says its coverage was observed at runtime, that
    # is the evidence — no separate store needed. The promotion step already
    # rewrites entries to `runtime-observed` from what a run watched happen,
    # so frugality arrives through the same path that corrects the claims.
    observed = dict(observed or {})
    for entry in library:
        if entry.get("coverage_provenance") == "runtime-observed":
            observed.setdefault(
                entry["id"], {_normalise(f) for f in entry.get("covers_files") or []}
            )

    scripts: list[str] = []
    skipped: list[dict[str, str]] = []
    for entry in library:
        script_id = entry["id"]
        seen = {_normalise(f) for f in observed.get(script_id, set())}
        declared_files = {_normalise(f) for f in entry.get("covers_files") or []}
        declared_modules = {_normalise(m) for m in entry.get("covers_modules") or []}

        matches_declared = bool(declared_files & wanted) or any(
            f == m or f.startswith(f"{m}/") for f in wanted for m in declared_modules
        )
        if seen:
            # Observation is complete by construction: it is what the script
            # actually requested. It decides both ways.
            if seen & wanted:
                scripts.append(script_id)
            else:
                skipped.append(
                    {
                        "script": script_id,
                        "why": "no file it was observed to exercise is in the "
                        "obligation for this change",
                    }
                )
            continue

        if matches_declared:
            scripts.append(script_id)
        else:
            # Kept, and said out loud. Excluding on a hand-written claim is a
            # bet that the claim is complete, and losing that bet means a
            # regression nobody ran the test for.
            scripts.append(script_id)
            skipped.append(
                {
                    "script": script_id,
                    "why": "kept for want of observed coverage — its declared scope "
                    "does not match this change, but a declaration cannot license "
                    "an exclusion",
                }
            )

    reasons = [
        f"{len(scripts)}/{len(library)} script(s) required by {len(wanted)} obliged file(s)"
    ]
    return Selection(
        scripts=sorted(set(scripts)),
        strategy="targeted",
        reasons=reasons,
        skipped=skipped,
        obliged_files=sorted(wanted),
    )
