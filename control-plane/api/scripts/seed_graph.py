#!/usr/bin/env python
"""Point the platform at a repository and seed the context graph from it.

    uv run python scripts/seed_graph.py --repo subhachak/agentic-sdlc
    uv run python scripts/seed_graph.py --local ../../            # a checkout

Reads source and parses imports. It never executes anything it fetches.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.adapters.registry import build_entity_resolver  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.core.context_graph import SqlContextGraph  # noqa: E402
from app.core.db import init_db  # noqa: E402
from app.core.seeding import seed  # noqa: E402


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", help="owner/name on GitHub")
    parser.add_argument("--ref", default="main")
    parser.add_argument("--local", help="index a directory instead of GitHub")
    parser.add_argument("--depth", type=int, default=None, help="component granularity")
    parser.add_argument("--dry-run", action="store_true", help="index but do not write")
    args = parser.parse_args()

    if not (args.repo or args.local):
        parser.error("give --repo owner/name or --local <path>")

    settings = get_settings()
    depth = args.depth or settings.code_index_max_depth

    if args.local:
        from app.adapters.code_intelligence.local_path import LocalPathCodeIntelligence

        indexer = LocalPathCodeIntelligence(Path(args.local), max_depth=depth)
        repo, ref = "", "local"
    else:
        from app.adapters.code_intelligence.github import GitHubCodeIntelligence

        indexer = GitHubCodeIntelligence(token=settings.github_token, max_depth=depth)
        repo, ref = args.repo, args.ref

    if args.dry_run:
        index = await indexer.index(repo, ref)
        print(f"{len(index.components)} components, {len(index.files)} files, "
              f"{len(index.dependencies)} dependencies "
              f"({index.unresolved_imports} unresolved imports)")
        for dep in sorted(index.dependencies, key=lambda d: -d.weight)[:15]:
            print(f"  {dep.source} -> {dep.target}  (x{dep.weight})")
        return 0

    await init_db()
    graph = SqlContextGraph(build_entity_resolver(settings))
    summary = await seed(graph, indexer, repo=repo, ref=ref)

    print(f"seeded {summary['repo']}@{summary['ref']}")
    for key in ("components", "files", "dependencies", "edges_written",
                "unresolved_imports", "skipped_files"):
        print(f"  {key:20s} {summary[key]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
