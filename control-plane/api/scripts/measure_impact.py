#!/usr/bin/env python
"""Measure the blast radius against what developers actually changed together.

Reads commit histories, holds out one file at a time, and asks the graph which
other files a change there could reach. Reports the graph against two
baselines, because a recall figure on its own means nothing: "everything"
scores perfect recall, and "the same directory" is the answer you get with no
dependency analysis at all.

Writes JSON so the number can regress visibly instead of being re-derived by
hand whenever someone asks how good the blast radius is.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.adapters.registry import build_entity_resolver  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.core.context_graph import SqlContextGraph  # noqa: E402
from app.core.db import init_db  # noqa: E402
from app.core.impact_eval import (  # noqa: E402
    build_cases,
    directory_predictor,
    everything_predictor,
    graph_predictor,
    score,
)

REPO_ROOT = Path(__file__).resolve().parents[3]


def read_history(limit: int) -> dict[str, set[str]]:
    """Which files each commit touched, from git rather than from a diff.

    `--name-only -z` for the same reason the QA plane uses `--name-status`:
    a rename must report the path that exists, and a path containing a space
    must survive.
    """
    result = subprocess.run(
        ["git", "log", f"-{limit}", "--no-merges", "--pretty=format:%x00commit %H",
         "--name-only", "-z"],
        cwd=REPO_ROOT, capture_output=True, text=True, check=True,
    )

    commits: dict[str, set[str]] = {}
    current = ""
    for field in result.stdout.split("\0"):
        entry = field.strip()
        if not entry:
            continue
        if entry.startswith("commit "):
            current = entry.split(" ", 1)[1].strip()
            commits[current] = set()
        elif current:
            commits[current].add(entry)
    return commits


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--commits", type=int, default=200)
    parser.add_argument("--depth", type=int, default=1)
    parser.add_argument("--max-files", type=int, default=20,
                        help="skip commits larger than this — above it, co-change "
                             "is a rename sweep rather than coupling")
    parser.add_argument("--out", type=Path, default=Path("evals/results/impact-accuracy.json"))
    parser.add_argument("--sweep", type=str, default="",
                        help="comma-separated depths to compare, e.g. 1,2,3,4")
    args = parser.parse_args()

    await init_db()
    graph = SqlContextGraph(build_entity_resolver(get_settings()))
    provenance = await graph.index_provenance()
    paths = await graph.module_paths()
    known = {p for group in paths.values() for p in group}

    if not known:
        print("the graph holds no files — seed it first", file=sys.stderr)
        return 1

    history = read_history(args.commits)
    cases = build_cases(history, known_files=known, max_files=args.max_files)
    if not cases:
        print("no usable commits in the window", file=sys.stderr)
        return 1

    with_http = await graph.file_dependents()
    imports_only = await graph.file_dependents(include_contracts=False)

    depths = (
        [int(d) for d in args.sweep.split(",") if d.strip()] if args.sweep else [args.depth]
    )
    reports = []
    for depth in depths:
        label = f" @depth {depth}" if len(depths) > 1 else ""
        reports.append(
            score(f"graph (imports + contracts){label}", cases,
                  graph_predictor(with_http, depth))
        )
        reports.append(
            score(f"graph (imports only){label}", cases, graph_predictor(imports_only, depth))
        )
    reports.append(score("baseline: same directory", cases, directory_predictor(known)))
    reports.append(score("baseline: whole repository", cases, everything_predictor(known)))

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "graph": provenance,
        "corpus": {
            "commits_scanned": len(history),
            "commits_used": len({c.commit for c in cases}),
            "cases": len(cases),
            "depths": depths,
            "max_files_per_commit": args.max_files,
            "ground_truth": "co-change: files committed together",
        },
        "reports": [r.as_dict() for r in reports],
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2) + "\n")

    print(f"corpus: {payload['corpus']['cases']} cases from "
          f"{payload['corpus']['commits_used']} commits "
          f"(graph at {(provenance.get('commit_sha') or '?')[:7]}, "
          f"depth {','.join(str(d) for d in depths)})\n")
    header = f"{'predictor':42} {'recall':>8} {'precision':>10} {'radius':>8} {'full hits':>10}"
    print(header)
    print("-" * len(header))
    for report in reports:
        print(f"{report.name:42} {report.recall:>8.1%} {report.precision:>10.1%} "
              f"{report.mean_radius:>8.1f} {report.perfect:>6}/{report.cases}")
    print(f"\nwritten to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
