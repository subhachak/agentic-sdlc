#!/usr/bin/env python
"""Do the control plane and the execution plane agree on what a change reaches?

They have to. The design gate reasons about one blast radius and QA scopes
regression against another, and a run whose two halves disagree about what a
change touches is a run that cannot justify its own verdict.

Today they agree on every commit measured — but incidentally, not
structurally. The graph carries one edge type, and an IMPORTS path stays
above the confidence floor until nine hops while the policy stops at two. So
every distinction the canonical engine draws (edge semantics, direction,
propagation by change kind, confidence decay) collapses to the flat walk the
execution plane does. Populate CALLS_ENDPOINT, register anything `inferred`,
or raise max_depth, and the two answers separate.

This exists so that separation is a failing check rather than a discovery.
Run it against a real exported graph and real commits — a disagreement that
only appears on invented input is not one anybody will hit.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "execution-plane" / "qa"))


def change_sets(repo: Path, scope: str, known: set[str], limit: int):
    """Real commits, restricted to the indexed scope."""
    shas = subprocess.run(
        ["git", "log", "--format=%H", "-n", str(limit), "--", scope],
        cwd=repo, capture_output=True, text=True, check=True,
    ).stdout.split()
    for sha in shas:
        files = subprocess.run(
            ["git", "show", "--name-only", "--format=", sha],
            cwd=repo, capture_output=True, text=True, check=True,
        ).stdout.split()
        touched = [f for f in files if f.startswith(scope) and f in known]
        if touched:
            yield sha[:7], touched


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graph", required=True, help="an exported code-graph.json")
    parser.add_argument("--repo", required=True, help="checkout the graph describes")
    parser.add_argument("--commits", type=int, default=60)
    parser.add_argument("--json", default="", help="write the report here")
    args = parser.parse_args()

    graph = json.loads(Path(args.graph).read_text())
    dependents = {k: set(v) for k, v in graph["file_dependents"].items()}
    policy = graph["impact"]["policy"]
    known = set(dependents) | {d for v in dependents.values() for d in v}

    from app.core.design_review import assess_change
    from orchestrator import context as execution_plane

    # The execution plane reads its graph from a path, and this comparison is
    # only meaningful if both sides read the *same* one.
    if execution_plane.CODE_GRAPH_FILE.resolve() != Path(args.graph).resolve():
        print(f"! set QA_CODE_GRAPH={args.graph} so both planes read one graph")
        return 2

    rows, disagreed = [], []
    for sha, files in change_sets(Path(args.repo), graph["scope"], known, args.commits):
        control = assess_change(files, dependents, depth=policy["max_depth"], known=known)
        control_modules = execution_plane.modules_for_paths(
            sorted(set(control.affected) | set(files))
        )
        execution_modules = execution_plane.blast_radius(
            execution_plane.modules_for_paths(files), files
        )

        row = {
            "commit": sha,
            "files": len(files),
            "control": sorted(control_modules),
            "execution": sorted(execution_modules),
            "only_execution": sorted(execution_modules - control_modules),
            "only_control": sorted(control_modules - execution_modules),
        }
        rows.append(row)
        if row["only_execution"] or row["only_control"]:
            disagreed.append(row)

    report = {
        "graph": graph["provenance"]["commit_sha"],
        "repo": graph["provenance"]["repo"],
        "scope": graph["scope"],
        "policy": policy,
        # Why an agreement here is weaker evidence than it looks.
        "edge_types_populated": sorted(
            {"IMPORTS"} if dependents else set()
        ),
        "change_sets": len(rows),
        "disagreed": len(disagreed),
        "disagreements": disagreed,
    }
    if args.json:
        Path(args.json).write_text(json.dumps(report, indent=2))

    print(f"{report['repo']} @ {report['graph'][:7]}  scope={report['scope']}")
    print(f"policy max_depth={policy['max_depth']} min_confidence={policy['min_confidence']}")
    print(f"edge types populated: {', '.join(report['edge_types_populated']) or 'none'}")
    print(f"\n{len(rows)} change sets, {len(disagreed)} disagreements")
    for row in disagreed[:20]:
        print(f"  {row['commit']}  +exec {row['only_execution']}  +control {row['only_control']}")

    if disagreed:
        print(
            "\nThe two planes no longer answer the same question. Consolidate on "
            "app/core/impact.py rather than reconciling the outputs."
        )
    return 1 if disagreed else 0


if __name__ == "__main__":
    raise SystemExit(main())
