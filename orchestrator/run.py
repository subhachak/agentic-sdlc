"""CLI entrypoint. Invoked by .github/workflows/agentic-qa.yml after a PR
merges to main. Builds the diff, loads requirement context, runs the graph,
and exits non-zero on gate failure so the Action run itself reflects status.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import yaml

from orchestrator.graph import build_graph

REPO_ROOT = Path(__file__).resolve().parents[1]


def get_diff(base_sha: str, head_sha: str) -> str:
    result = subprocess.run(
        ["git", "diff", f"{base_sha}..{head_sha}", "--", "sample-app/", "features.yaml"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def get_features() -> dict:
    path = REPO_ROOT / "features.yaml"
    return yaml.safe_load(path.read_text()) if path.exists() else {}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True, help="owner/name")
    parser.add_argument("--pr-number", required=True, type=int)
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--head-sha", required=True)
    args = parser.parse_args()

    diff_text = get_diff(args.base_sha, args.head_sha)
    if not diff_text.strip():
        print("No relevant changes in sample-app/ or features.yaml — skipping QA pipeline.")
        return 0

    graph = build_graph()
    initial_state = {
        "repo": args.repo,
        "pr_number": args.pr_number,
        "base_sha": args.base_sha,
        "head_sha": args.head_sha,
        "diff_text": diff_text,
        "features_context": get_features(),
    }

    final_state = graph.invoke(initial_state)

    print(json.dumps(
        {
            "gate_passed": final_state.get("gate_passed"),
            "test_plan_gate_passed": final_state.get("test_plan_gate_passed"),
            "pr_comment_url": final_state.get("pr_comment_url"),
            "defects_created": final_state.get("defects_created"),
        },
        indent=2,
    ))

    return 0 if final_state.get("gate_passed") else 1


if __name__ == "__main__":
    sys.exit(main())
