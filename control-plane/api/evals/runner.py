"""Run a phase repeatedly against fixed inputs and report the distribution.

The suite tests that the plumbing is correct. Nothing in it tests whether the
agents are any good, so every claim about output quality has rested on single
observed runs — which is an anecdote, not a measurement.

This runs one phase N times against the same graph and the same requirement,
scores each run against properties that can be checked without judgment, and
reports accept rate, expectation rate and stability. Phases are exercised
individually rather than through a full cycle: a design eval is N cheap model
calls with no browser, so a regression is affordable to detect.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from app.agents.design import SYSTEM as DESIGN_SYSTEM
from app.agents.design import DesignProposal
from app.agents.design import build_prompt as build_design_prompt
from app.agents.implementation import SYSTEM as IMPLEMENTATION_SYSTEM
from app.agents.implementation import Implementation
from app.agents.implementation import build_prompt as build_implementation_prompt
from app.core.change_review import review as review_change
from app.core.design_review import MAX_FILES
from app.core.design_review import review as review_design
from evals.scoring import CaseResult, Outcome, check_expectations

CASES_DIR = Path(__file__).parent / "cases"


@dataclass
class Case:
    name: str
    phase: str
    requirement: str
    expects: dict[str, Any]
    design: dict[str, Any] | None = None  # for implementation cases

    @classmethod
    def load(cls, path: Path) -> "Case":
        raw = yaml.safe_load(path.read_text())
        return cls(
            name=raw.get("name", path.stem),
            phase=raw["phase"],
            requirement=raw["requirement"],
            expects=raw.get("expects", {}) or {},
            design=raw.get("design"),
        )


def load_cases(phase: str | None = None) -> list[Case]:
    cases = [Case.load(p) for p in sorted(CASES_DIR.rglob("*.yaml"))]
    return [c for c in cases if phase in (None, c.phase)]


async def run_design(case: Case, llm, graph, source_control=None) -> Outcome:
    catalogue = await graph.module_catalogue()
    known = await graph.module_paths()
    file_dependents = await graph.file_dependents()
    criteria = await graph.criteria()

    prompt = build_design_prompt(
        requirement=case.requirement,
        criteria=criteria,
        catalogue=catalogue,
        snippets=[],
        max_files=MAX_FILES,
    )
    try:
        proposal = await llm.complete_json(DESIGN_SYSTEM, prompt, DesignProposal)
    except Exception as exc:  # noqa: BLE001 - a provider failure is a data point
        return Outcome(False, error=str(exc)[:200])

    if proposal.blocked:
        return Outcome(False, blocked=proposal.blocked, modules=proposal.modules,
                       files=proposal.files)

    verdict = review_design(
        proposal.model_dump(),
        known_modules=known,
        file_dependents=file_dependents,
        known_criteria={c["id"] for c in criteria if c.get("id")},
    )
    return Outcome(
        accepted=verdict.allowed,
        modules=proposal.modules,
        files=proposal.files,
        reasons=verdict.reasons,
    )


async def run_implementation(case: Case, llm, graph, source_control) -> Outcome:
    design = case.design or {}
    allowed = design.get("modules", [])
    paths = design.get("files", [])
    files = await source_control.read_files(design.get("repo", ""), design.get("ref", "main"), paths)

    prompt = build_implementation_prompt(
        requirement=case.requirement,
        design=design,
        criteria=await graph.criteria(),
        files=files,
        allowed_modules=allowed,
    )
    try:
        proposal = await llm.complete_json(IMPLEMENTATION_SYSTEM, prompt, Implementation)
    except Exception as exc:  # noqa: BLE001
        return Outcome(False, error=str(exc)[:200])

    if proposal.blocked:
        return Outcome(False, blocked=proposal.blocked)

    edits = [e.model_dump() for e in proposal.edits]
    verdict = review_change(
        edits, allowed_modules=allowed, known_modules=await graph.module_paths()
    )
    return Outcome(
        accepted=verdict.allowed,
        files=[e["path"] for e in edits],
        modules=verdict.modules,
        reasons=verdict.reasons,
    )


RUNNERS = {"design": run_design, "implementation": run_implementation}


async def run_case(case: Case, *, llm, graph, source_control=None, repeats: int = 3) -> CaseResult:
    runner = RUNNERS[case.phase]
    # Sequential on purpose: concurrent runs against one provider produce rate
    # limiting that would be scored as agent failure.
    runs = [await runner(case, llm, graph, source_control) for _ in range(repeats)]
    failures = [check_expectations(r, case.expects) for r in runs]
    return CaseResult(
        case.name, case.phase, runs, failures,
        expects_decline=bool(case.expects.get("blocked")),
    )


def report(results: list[CaseResult]) -> str:
    lines = [
        f"{'case':34s} {'phase':15s} {'accept':>7s} {'expect':>7s} {'stability':>10s}",
        "-" * 78,
    ]
    for r in results:
        s = r.summary()
        accept = f"{s['decline_rate']:>6.0%}*" if r.expects_decline else f"{s['accept_rate']:>7.0%}"
        stab = "     n/a" if r.expects_decline else f"{s['file_stability']:>10.0%}"
        lines.append(f"{s['case'][:33]:34s} {s['phase']:15s} {accept} {s['expectation_rate']:>7.0%} {stab}")

    producing = [r for r in results if not r.expects_decline]
    if results:
        lines.append("-" * 78)
        overall_expect = sum(r.expectation_rate for r in results) / len(results)
        overall_accept = (
            sum(r.accept_rate for r in producing) / len(producing) if producing else 0.0
        )
        lines.append(
            f"{'overall':34s} {'':15s} {overall_accept:>7.0%} {overall_expect:>7.0%}"
        )
        if any(r.expects_decline for r in results):
            lines.append("* declined, which is what the case expects")
    for r in results:
        for failure in r.summary()["failures"]:
            lines.append(f"  {r.case}: {'; '.join(failure)}")
    return "\n".join(lines)


async def run_all(*, llm, graph, source_control=None, phase=None, repeats=3) -> list[CaseResult]:
    return [
        await run_case(c, llm=llm, graph=graph, source_control=source_control, repeats=repeats)
        for c in load_cases(phase)
    ]
