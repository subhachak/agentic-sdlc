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
        result = subprocess.run(
            ["git", *args], cwd=self._root, capture_output=True, text=True
        )
        if result.returncode != 0:
            raise RuntimeError(f"git {' '.join(args)}: {result.stderr.strip()}")
        return result.stdout.strip()

    async def read_files(self, repo: str, ref: str, paths: list[str]) -> dict[str, str]:
        out: dict[str, str] = {}
        for path in paths:
            candidate = self._root / path
            if candidate.is_file():
                out[path] = candidate.read_text(encoding="utf-8", errors="replace")
        return out

    async def open_change(
        self, repo, base_ref, branch, title, body, edits: list[FileEdit]
    ) -> ChangeRef:
        original = self._git("rev-parse", "--abbrev-ref", "HEAD")
        self._git("checkout", "-B", branch)
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
            files=[e.path for e in edits],
            url=None,
        )
