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

from orchestrator import data_store
from orchestrator.context import build_assertions
from orchestrator.graph import build_graph
from orchestrator.nodes.diff_analysis import changed_paths_from_name_status
from orchestrator.nodes import report as report_node
from orchestrator.paths import DIFF_PATHS, FEATURES_FILE, REPO_ROOT


def get_diff(base_sha: str, head_sha: str) -> str:
    result = subprocess.run(
        ["git", "diff", f"{base_sha}..{head_sha}", "--", *DIFF_PATHS],
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


def get_changed_paths(base_sha: str, head_sha: str) -> list[str]:
    """Which files changed, from git rather than from the diff text.

    `--name-status -z` is the deterministic source: it distinguishes a rename
    from a delete-plus-add and survives paths containing spaces, neither of
    which the `diff --git` headers can express. Scope derived from the header
    parse pointed a rename at the pre-rename path, which no longer exists.
    """
    result = subprocess.run(
        ["git", "diff", "--name-status", "-z", f"{base_sha}..{head_sha}", "--", *DIFF_PATHS],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"git diff --name-status {base_sha}..{head_sha} failed\n{result.stderr.strip()}"
        )
    return changed_paths_from_name_status(result.stdout)


def get_features() -> dict:
    return yaml.safe_load(FEATURES_FILE.read_text()) if FEATURES_FILE.exists() else {}


def _run_phase(args) -> dict:
    diff_text = get_diff(args.base_sha, args.head_sha)
    if not diff_text.strip():
        print("No relevant changes in demo-app/ or features.yaml — skipping QA pipeline.")
        return {}

    # The store is restored whatever happens. Seeding is additive and had no
    # teardown; that only looked safe because both real execution paths throw
    # the checkout away afterwards. A developer running this against their
    # working copy was permanently editing a tracked file.
    original = data_store.snapshot()
    try:
        state = _invoke(args, diff_text)
    finally:
        if data_store.restore(original):
            print("Restored the data store to its pre-run contents.")
    return state


def _invoke(args, diff_text: str) -> dict:
    return build_graph().invoke(
        {
            "repo": args.repo,
            "pr_number": args.pr_number,
            "base_sha": args.base_sha,
            "head_sha": args.head_sha,
            "diff_text": diff_text,
            "changed_paths": get_changed_paths(args.base_sha, args.head_sha),
            "head_sha_for_graph": args.head_sha,
            "features_context": get_features(),
        }
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True, help="owner/name")
    # Optional. A nightly regression against a branch has no pull request,
    # and requiring one forbade a legitimate run — the pipeline would refuse
    # to start rather than run and simply post nowhere.
    parser.add_argument(
        "--pr-number",
        type=int,
        default=0,
        help="the change request to report against, when there is one",
    )
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
            # The graph edges this run observed travel with the result. The
            # control plane ingests them with provenance; nothing here writes
            # to the graph directly, because this job is the untrusted half.
            payload = {k: v for k, v in state.items() if k != "diff_text"}
            payload["assertions"] = build_assertions(state)
            args.state_file.write_text(json.dumps(payload, indent=2))
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
