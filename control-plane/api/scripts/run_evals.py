#!/usr/bin/env python
"""Measure the agents, not the plumbing.

    uv run python scripts/run_evals.py --repeats 5
    uv run python scripts/run_evals.py --phase design --repo owner/name

Seeds the context graph from a repository, then runs each case that many times
and reports accept rate, expectation rate and stability. Model calls cost
money and take time, so repeats defaults low and phases can be run alone.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.adapters.registry import build_entity_resolver, build_source_control  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.core.context_graph import SqlContextGraph  # noqa: E402
from app.core.db import init_db  # noqa: E402
from app.core.seeding import seed  # noqa: E402
from evals.runner import report, run_all  # noqa: E402

RESULTS = Path(__file__).resolve().parent.parent / "evals" / "results"


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--phase", choices=("design", "implementation"))
    parser.add_argument("--repo", default="subhachak/agentic-sdlc")
    parser.add_argument("--ref", default="main")
    parser.add_argument("--skip-seed", action="store_true")
    parser.add_argument("--label", default="", help="recorded with the results")
    args = parser.parse_args()

    settings = get_settings()
    if settings.llm_provider_adapter != "claude":
        print("These evals measure a model. Set LLM_PROVIDER_ADAPTER=claude.", file=sys.stderr)
        return 1

    await init_db()
    graph = SqlContextGraph(build_entity_resolver(settings))

    if not args.skip_seed:
        from app.adapters.code_intelligence.github import GitHubCodeIntelligence

        print(f"seeding the graph from {args.repo}@{args.ref}...")
        await seed(graph, GitHubCodeIntelligence(token=settings.github_token),
                   repo=args.repo, ref=args.ref)

    from app.adapters.llm.claude_adapter import ClaudeLLMProvider

    llm = ClaudeLLMProvider(api_key=settings.anthropic_api_key, model=settings.claude_model)

    results = await run_all(
        llm=llm,
        graph=graph,
        source_control=build_source_control(settings),
        phase=args.phase,
        repeats=args.repeats,
    )
    print()
    print(report(results))

    # Recorded so a prompt or model change can be compared against what came
    # before, which is the only way to tell an upgrade from a regression.
    RESULTS.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = RESULTS / f"{stamp}.json"
    out.write_text(json.dumps({
        "at": stamp,
        "label": args.label,
        "model": settings.claude_model,
        "repo": args.repo,
        "repeats": args.repeats,
        "results": [r.summary() for r in results],
    }, indent=2))
    print(f"\nrecorded to {out.relative_to(Path.cwd())}")

    weak = [r for r in results if r.expectation_rate < 1.0]
    return 1 if weak else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
