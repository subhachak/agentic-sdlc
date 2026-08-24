"""Which commit the QA phase actually tests.

The defect these pin: the dispatch node read `base_sha` and `head_sha` out of
state, and nothing ever wrote them. A remote run therefore received two empty
strings, and its workflow fell back to `github.sha` — the default branch. It
tested the code that was already there and reported a verdict on a change it
had never seen, which is indistinguishable from a passing QA result.

Everything scoped to that diff — blast radius, required regressions, the gate
— was correctly computed against the wrong commit.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.adapters.source_control.local_working_copy import LocalWorkingCopy
from app.ports.source_control import FileEdit


def _repo(tmp_path: Path) -> Path:
    def git(*args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=tmp_path, capture_output=True, text=True, check=True
        ).stdout.strip()

    git("init", "-b", "main")
    git("config", "user.email", "t@example.com")
    git("config", "user.name", "T")
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "page.tsx").write_text("export const V = 1;\n")
    git("add", ".")
    git("commit", "-m", "base")
    return tmp_path


# --- the revision pair -----------------------------------------------------


@pytest.mark.asyncio
async def test_a_change_reports_both_the_commit_it_made_and_the_one_it_came_from(tmp_path):
    """Without the base there is no pair to diff, and a QA run has nothing to
    scope a blast radius between."""
    root = _repo(tmp_path)
    change = await LocalWorkingCopy(root).open_change(
        "acme/thing", "main", "agentic/abc", "t", "b",
        [FileEdit(path="app/page.tsx", content="export const V = 2;\n")],
    )

    assert len(change.commit) == 40
    assert len(change.base_commit) == 40
    assert change.commit != change.base_commit


@pytest.mark.asyncio
async def test_the_branch_is_cut_from_the_requested_base_not_from_wherever_head_is(tmp_path):
    """`checkout -B <branch>` alone cuts from current HEAD, so a second run
    branched off the first run's branch — and the diff described neither
    change."""
    root = _repo(tmp_path)
    adapter = LocalWorkingCopy(root)

    first = await adapter.open_change(
        "acme/thing", "main", "agentic/one", "one", "b",
        [FileEdit(path="app/page.tsx", content="export const V = 2;\n")],
    )
    subprocess.run(["git", "checkout", "agentic/one"], cwd=root, capture_output=True, check=True)

    second = await adapter.open_change(
        "acme/thing", "main", "agentic/two", "two", "b",
        [FileEdit(path="app/page.tsx", content="export const V = 3;\n")],
    )

    assert second.base_commit == first.base_commit
    assert second.base_commit != first.commit


@pytest.mark.asyncio
async def test_an_unresolvable_base_falls_back_rather_than_failing(tmp_path):
    root = _repo(tmp_path)
    change = await LocalWorkingCopy(root).open_change(
        "acme/thing", "no-such-branch", "agentic/x", "t", "b",
        [FileEdit(path="app/page.tsx", content="export const V = 2;\n")],
    )
    assert len(change.base_commit) == 40


# --- reading at a revision -------------------------------------------------


@pytest.mark.asyncio
async def test_files_are_read_at_the_requested_ref_not_from_the_working_tree(tmp_path):
    """The agent asked to patch `main` used to be shown the working tree —
    including uncommitted edits and the result of a previous run."""
    root = _repo(tmp_path)
    adapter = LocalWorkingCopy(root)
    (root / "app" / "page.tsx").write_text("export const V = 999;  // uncommitted\n")

    at_main = await adapter.read_files("acme/thing", "main", ["app/page.tsx"])
    from_disk = await adapter.read_files("acme/thing", "", ["app/page.tsx"])

    assert at_main["app/page.tsx"] == "export const V = 1;\n"
    assert "uncommitted" in from_disk["app/page.tsx"]


@pytest.mark.asyncio
async def test_an_unresolvable_ref_falls_back_to_the_working_tree(tmp_path):
    """A demo pointed at a directory that is not a repository should still
    work."""
    root = _repo(tmp_path)
    files = await LocalWorkingCopy(root).read_files("acme/thing", "nope", ["app/page.tsx"])
    assert files["app/page.tsx"] == "export const V = 1;\n"


@pytest.mark.asyncio
async def test_a_file_absent_at_that_revision_is_omitted_not_invented(tmp_path):
    root = _repo(tmp_path)
    files = await LocalWorkingCopy(root).read_files("acme/thing", "main", ["app/added-later.tsx"])
    assert files == {}


# --- refusing to dispatch without one --------------------------------------


@pytest.mark.asyncio
async def test_a_dispatch_with_no_revision_is_refused_before_anything_is_triggered():
    """`workflow_dispatch` cannot decline a run for a missing input — it would
    start, check out its own default branch, and report a verdict on code the
    run never touched."""
    from app.adapters.work_dispatch.github_actions import GitHubActionsWorkDispatch

    dispatcher = GitHubActionsWorkDispatch(repo="acme/thing", token="t")

    with pytest.raises(ValueError, match="no head revision"):
        await dispatcher.trigger("run-1", "qa", "nonce", {"base_sha": "a" * 40, "head_sha": ""})


def test_the_workflow_checks_out_the_dispatched_revision():
    """The `github.sha` fallback is what made a dispatched run test main."""
    import yaml

    workflow = yaml.safe_load(
        (Path(__file__).resolve().parents[3] / ".github/workflows/agentic-qa.yml").read_text()
    )
    checkout = workflow["jobs"]["qa-run"]["steps"][0]

    assert "inputs.head_sha" in checkout["with"]["ref"]
    assert checkout["with"]["ref"].strip().startswith("${{ inputs.head_sha")
