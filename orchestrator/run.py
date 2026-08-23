"""CLI entrypoint. Invoked by .github/workflows/agentic-qa.yml after a PR
merges to main.

The pipeline is split into two phases on purpose:

  --phase run     builds the diff, runs the graph through the gate, and
                  writes the resulting state to --state-file. This phase
                  executes agent-generated Playwright specs, so its job is
                  given no GitHub write token.

  --phase report  reads that state file and posts to GitHub. It makes no
                  LLM calls and executes none of the generated code, so it
                  is safe to give it issues:write and pull-requests:write.

  --phase all     both, in one process — for local dry runs.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import yaml

from orchestrator.graph import build_graph
from orchestrator.nodes import report as report_node

REPO_ROOT = Path(__file__).resolve().parents[1]


def get_diff(base_sha: str, head_sha: str) -> str:
    result = subprocess.run(
        ["git", "diff", f"{base_sha}..{head_sha}", "--", "sample-app/", "features.yaml"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"git diff {base_sha}..{head_sha} failed — are both commits present in this "
            f"checkout? (fetch-depth: 0 is required)\n{result.stderr.strip()}"
        )
    return result.stdout


def get_features() -> dict:
    path = REPO_ROOT / "features.yaml"
    return yaml.safe_load(path.read_text()) if path.exists() else {}


def _run_phase(args) -> dict:
    diff_text = get_diff(args.base_sha, args.head_sha)
    if not diff_text.strip():
        print("No relevant changes in sample-app/ or features.yaml — skipping QA pipeline.")
        return {}

    return build_graph().invoke(
        {
            "repo": args.repo,
            "pr_number": args.pr_number,
            "base_sha": args.base_sha,
            "head_sha": args.head_sha,
            "diff_text": diff_text,
            "features_context": get_features(),
        }
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True, help="owner/name")
    parser.add_argument("--pr-number", required=True, type=int)
    parser.add_argument("--base-sha")
    parser.add_argument("--head-sha")
    parser.add_argument("--phase", choices=("run", "report", "all"), default="all")
    parser.add_argument(
        "--state-file",
        type=Path,
        help="where --phase run writes its state, and --phase report reads it",
    )
    args = parser.parse_args()

    # Validate arguments before doing any work: discovering a missing
    # --state-file after the graph has run costs a full Playwright execution
    # and a handful of model calls.
    if args.phase in ("run", "all") and not (args.base_sha and args.head_sha):
        parser.error("--base-sha and --head-sha are required for this phase")
    if args.phase == "run" and not args.state_file:
        parser.error("--state-file is required for --phase run")

    if args.phase in ("run", "all"):
        state = _run_phase(args)
        if args.phase == "run":
            # The diff can be large and nothing downstream reads it.
            args.state_file.write_text(
                json.dumps({k: v for k, v in state.items() if k != "diff_text"}, indent=2)
            )
            print(f"Wrote pipeline state to {args.state_file}")
            # Exit 0 even on gate failure: the report phase still has to run,
            # and it is the one that turns the workflow red.
            return 0
    else:
        if not args.state_file or not args.state_file.exists():
            print(f"No state file at {args.state_file} — the run phase produced nothing to report.")
            return 1
        state = json.loads(args.state_file.read_text())

    if not state:
        return 0

    final_state = report_node.run(state)

    print(json.dumps(
        {
            "gate_passed": final_state.get("gate_passed"),
            "test_plan_gate_passed": final_state.get("test_plan_gate_passed"),
            "test_plan_attempts": final_state.get("test_plan_attempts"),
            "pr_comment_url": final_state.get("pr_comment_url"),
            "defects_created": final_state.get("defects_created"),
        },
        indent=2,
    ))

    return 0 if final_state.get("gate_passed") else 1


if __name__ == "__main__":
    sys.exit(main())
