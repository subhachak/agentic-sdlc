"""Demo-default: propose a change against a working copy on disk.

Writes a real branch with a real commit, and stops there. No push, no pull
request, nothing that leaves the machine — so the full cycle is demonstrable
without a token and without anything appearing in a repository someone else
is watching.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from app.ports.source_control import ChangeRef, FileEdit


class LocalWorkingCopy:
    def __init__(self, root: Path) -> None:
        self._root = Path(root)

    def _git(self, *args: str) -> str:
        return self._git_raw(*args).strip()

    def _git_raw(self, *args: str) -> str:
        """Unstripped, for commands whose output *is* the answer.

        `git show <ref>:<path>` returns file content, and stripping it removes
        the trailing newline — so a file read at a revision differed from the
        same file on disk by one byte, and an agent handed that content wrote
        it back without its final newline.
        """
        result = subprocess.run(
            ["git", *args], cwd=self._root, capture_output=True, text=True
        )
        if result.returncode != 0:
            raise RuntimeError(f"git {' '.join(args)}: {result.stderr.strip()}")
        return result.stdout

    async def read_files(self, repo: str, ref: str, paths: list[str]) -> dict[str, str]:
        """Read files at a revision, not from whatever is on disk.

        The ref used to be ignored entirely, so an agent asked to write a
        patch against `main` was shown the working tree — including any
        uncommitted edit, and including the result of a previous run. Falls
        back to the working tree when the ref does not resolve, because a
        demo pointed at a directory that is not a git repository should still
        work.
        """
        if ref and self._resolves(ref):
            return self._read_at(ref, paths)

        out: dict[str, str] = {}
        for path in paths:
            candidate = self._root / path
            if candidate.is_file():
                out[path] = candidate.read_text(encoding="utf-8", errors="replace")
        return out

    def _resolves(self, ref: str) -> bool:
        try:
            self._git("rev-parse", "--verify", f"{ref}^{{commit}}")
        except RuntimeError:
            return False
        return True

    def _read_at(self, ref: str, paths: list[str]) -> dict[str, str]:
        out: dict[str, str] = {}
        for path in paths:
            try:
                out[path] = self._git_raw("show", f"{ref}:{path}")
            except RuntimeError:
                continue  # the file does not exist at that revision
        return out

    async def open_change(
        self, repo, base_ref, branch, title, body, edits: list[FileEdit]
    ) -> ChangeRef:
        original = self._git("rev-parse", "--abbrev-ref", "HEAD")
        # Branch from what the caller asked for. `checkout -B <branch>` alone
        # cuts from wherever HEAD happens to be, so a change meant to be based
        # on main was based on the previous run's branch — and the diff a QA
        # run computed from it described neither change.
        base = base_ref if base_ref and self._resolves(base_ref) else original
        base_commit = self._git("rev-parse", base)
        self._git("checkout", "-B", branch, base)
        try:
            for edit in edits:
                target = self._root / edit.path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(edit.content)
                self._git("add", edit.path)
            self._git("commit", "-m", f"{title}\n\n{body}")
            commit = self._git("rev-parse", "HEAD")
        finally:
            # Leave the working copy where it was found. The branch stays, so
            # the change is inspectable; the checkout does not linger.
            self._git("checkout", original)

        return ChangeRef(
            provider="local-working-copy",
            branch=branch,
            commit=commit,
            base_commit=base_commit,
            files=[e.path for e in edits],
            url=None,
        )
