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
    parser.add_argument("--depth", type=int, default=None, help="module granularity")
    parser.add_argument("--project", default="default",
                        help="which project's graph to write; each is isolated")
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
        prov = index.provenance
        print(f"{index.repo}@{prov.commit_sha or 'UNPINNED'} "
              f"(indexer {prov.indexer_version})")
        print(f"{len(index.modules)} modules, {len(index.files)} files, "
              f"{len(index.dependencies)} dependencies, "
              f"{len(index.imports)} file imports")
        print(f"resolution: {prov.internal_capture_rate:.1%} of internal imports captured "
              f"({prov.unresolved_internal} internal + {prov.unresolved_relative} relative "
              f"unresolved, {prov.external_package} external)")
        for spec, count in prov.most_missed[:10]:
            print(f"  missed x{count}  {spec}")
        for dep in sorted(index.dependencies, key=lambda d: -d.weight)[:15]:
            print(f"  {dep.source} -> {dep.target}  (x{dep.weight})")
        return 0

    await init_db()
    graph = SqlContextGraph(build_entity_resolver(settings))
    summary = await seed(graph, indexer, repo=repo, ref=ref, project=args.project)

    print(f"seeded {summary['repo']}@{summary['commit_sha'] or 'UNPINNED'} "
          f"(ref {summary['ref']}, indexer {summary['indexer_version']})")
    for key in ("modules", "files", "dependencies", "file_imports",
                "edges_written", "skipped_files"):
        print(f"  {key:20s} {summary[key]}")
    print(f"  {'removed':20s} {summary['removed']}")
    resolution = summary["resolution"]
    print(f"  {'capture rate':20s} {resolution['internal_capture_rate']:.1%} "
          f"({resolution['unresolved_internal']} internal imports dropped)")
    if not summary["pinned"]:
        print("  WARNING: this index names no commit and cannot be compared with another")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
