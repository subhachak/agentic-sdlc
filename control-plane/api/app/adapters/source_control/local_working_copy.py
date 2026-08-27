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

    def remote(self) -> str | None:
        """What repository this checkout actually points at, if any.

        Reported so the console can tell whether a local change target and a
        remote index describe the same codebase. They did not, and nothing
        was in a position to notice: retrieval read zero files and called
        itself built.
        """
        try:
            return self._git("remote", "get-url", "origin") or None
        except (RuntimeError, OSError):
            # Not a checkout, or no origin. Both are legitimate, and neither
            # is worth an exception for a label.
            return None

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

    async def changed_paths(self, repo: str, base_ref: str, head_ref: str) -> list[str]:
        """What the repository says changed, deletions included.

        Shares the `--name-status -z` parse with change_files and differs in
        exactly two ways, both of which matter to a blast radius: a deleted
        file is a change its dependents have to survive, and the source of a
        copy is unchanged while the copy itself is new code.
        """
        if not (self._resolves(base_ref) and self._resolves(head_ref)):
            return []

        raw = self._git_raw("diff", "--name-status", "-z", f"{base_ref}...{head_ref}")
        fields = [f for f in raw.split("\0") if f]

        paths: set[str] = set()
        index = 0
        while index < len(fields):
            status = fields[index]
            if status.startswith(("R", "C")) and index + 2 < len(fields):
                # Both ends, for a rename as well as a copy. The dependency
                # graph was built at the base commit, so a renamed file's
                # importers are recorded against the path that no longer
                # exists — pass only the new path and the lookup finds
                # nothing, which reads as a rename that broke nobody.
                paths.add(fields[index + 1])
                paths.add(fields[index + 2])
                index += 3
                continue
            if index + 1 < len(fields):
                paths.add(fields[index + 1])
            index += 2
        return sorted(paths)

    async def change_files(self, repo: str, base_ref: str, head_ref: str) -> list[FileEdit]:
        """What `head_ref` changed relative to `base_ref`.

        Names come from `--name-status -z` for the same reason the QA plane
        uses it: a rename must report the path that exists, and a path with a
        space in it must survive. Deleted files are skipped — there is no
        content at head to review, and a module losing a file is caught by the
        path check rather than by reading it.
        """
        if not (self._resolves(base_ref) and self._resolves(head_ref)):
            return []

        raw = self._git_raw("diff", "--name-status", "-z", f"{base_ref}...{head_ref}")
        fields = [f for f in raw.split("\0") if f]

        paths: list[str] = []
        index = 0
        while index < len(fields):
            status = fields[index]
            if status.startswith(("R", "C")) and index + 2 < len(fields):
                paths.append(fields[index + 2])
                index += 3
                continue
            if index + 1 < len(fields):
                if not status.startswith("D"):
                    paths.append(fields[index + 1])
            index += 2

        contents = self._read_at(head_ref, paths)
        return [FileEdit(path=path, content=contents[path]) for path in paths if path in contents]

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
