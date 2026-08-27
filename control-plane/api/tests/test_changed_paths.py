"""What the repository says changed, not what the agent said it wrote.

The blast radius is assessed once per phase, from the best evidence that
phase has. Design has a prediction — the files a proposal names.
Implementation has the actor's own account — the edit list it reported. The
QA phase has both commits, so it can ask git.

That difference is not academic. Between an agent's account and git's sit
formatters, commit hooks, rewrites that changed nothing, and any edit the
agent did not mention. Scoping regression from intent when effect is
available is weaker in the one direction that hurts: a path nobody reported
is a path nothing re-tests.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.adapters.source_control.local_working_copy import LocalWorkingCopy


def _repo(tmp_path: Path):
    def git(*args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=tmp_path, capture_output=True, text=True, check=True
        ).stdout.strip()

    git("init", "-b", "main")
    git("config", "user.email", "t@example.com")
    git("config", "user.name", "T")
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "page.tsx").write_text("export const V = 1;\n")
    (tmp_path / "app" / "old.ts").write_text("export const OLD = 1;\n")
    (tmp_path / "app" / "doomed.ts").write_text("export const D = 1;\n")
    git("add", ".")
    git("commit", "-m", "base")
    return tmp_path, git


@pytest.mark.asyncio
async def test_a_deletion_is_a_change_its_dependents_have_to_survive(tmp_path):
    """change_files skips deletions because there is no content at head to
    review. Impact cannot: removing a file is the change most likely to break
    whatever imported it, and a radius computed without it is narrow in
    exactly the direction that passes."""
    root, git = _repo(tmp_path)
    (root / "app" / "doomed.ts").unlink()
    git("commit", "-am", "remove")

    sc = LocalWorkingCopy(root)
    paths = await sc.changed_paths("acme/thing", "HEAD~1", "HEAD")
    edits = await sc.change_files("acme/thing", "HEAD~1", "HEAD")

    assert "app/doomed.ts" in paths
    assert "app/doomed.ts" not in [e.path for e in edits]


@pytest.mark.asyncio
async def test_a_rename_reports_the_path_that_no_longer_exists_too(tmp_path):
    """Its dependents are precisely what a rename can break."""
    root, git = _repo(tmp_path)
    git("mv", "app/old.ts", "app/new.ts")
    git("commit", "-m", "rename")

    paths = await LocalWorkingCopy(root).changed_paths("acme/thing", "HEAD~1", "HEAD")
    assert "app/new.ts" in paths
    assert "app/old.ts" in paths


@pytest.mark.asyncio
async def test_a_path_with_a_space_survives_the_parse(tmp_path):
    """`--name-status -z` rather than a whitespace split, for the same reason
    the execution plane uses it."""
    root, git = _repo(tmp_path)
    (root / "app" / "two words.ts").write_text("export const W = 1;\n")
    git("add", ".")
    git("commit", "-m", "spaced")

    paths = await LocalWorkingCopy(root).changed_paths("acme/thing", "HEAD~1", "HEAD")
    assert "app/two words.ts" in paths


@pytest.mark.asyncio
async def test_it_sees_an_edit_no_agent_reported(tmp_path):
    """The case the whole method exists for. A commit hook, a formatter, or
    an agent that under-reported — git knows, the edit list does not."""
    root, git = _repo(tmp_path)
    (root / "app" / "page.tsx").write_text("export const V = 2;\n")
    (root / "app" / "formatted-by-a-hook.ts").write_text("export const F = 1;\n")
    git("add", ".")
    git("commit", "-m", "change plus something nobody declared")

    paths = await LocalWorkingCopy(root).changed_paths("acme/thing", "HEAD~1", "HEAD")

    declared = ["app/page.tsx"]  # what an implementation agent would report
    assert set(paths) - set(declared) == {"app/formatted-by-a-hook.ts"}


@pytest.mark.asyncio
async def test_an_unresolvable_revision_yields_nothing_rather_than_raising(tmp_path):
    """The caller falls back to the weaker set and says which one it used;
    an exception here would fail the phase over a scope question."""
    root, _ = _repo(tmp_path)
    assert await LocalWorkingCopy(root).changed_paths("acme/thing", "nope", "HEAD") == []
