"""Doubles for the implementation phase.

The source-control double records what it was asked to propose without
writing anything, and the model double returns a change rather than refusing
— the mock adapter deliberately refuses, which is right for a demo and
useless for driving a graph test past this phase.
"""

from __future__ import annotations

from app.ports.llm_provider import LLMResponse
from app.ports.source_control import ChangeRef


class StubSourceControl:
    def __init__(self, files: dict[str, str] | None = None) -> None:
        self.files = files or {"demo-app/app/claims/page.tsx": "export default function X() {}\n"}
        self.opened: list[dict] = []

    async def read_files(self, repo, ref, paths):
        return {p: self.files[p] for p in paths if p in self.files}

    async def open_change(self, repo, base_ref, branch, title, body, edits):
        self.opened.append({"branch": branch, "title": title,
                            "files": [e.path for e in edits]})
        return ChangeRef(
            provider="stub", branch=branch, url=f"https://stub/pull/{len(self.opened)}",
            number=len(self.opened), commit="deadbeef",
            files=[e.path for e in edits],
        )


class WritingLLMProvider:
    """Returns one edit to the first file it was shown."""

    def __init__(self, *, blocked: str = "", path: str | None = None) -> None:
        self._blocked = blocked
        self._path = path

    async def complete(self, system_prompt, user_prompt, *, max_tokens=1024):
        return LLMResponse(text="[stub]", model="stub", input_tokens=1, output_tokens=1)

    async def complete_json(self, system_prompt, user_prompt, schema, *, max_tokens=16000):
        if self._blocked:
            return schema(summary="cannot proceed", blocked=self._blocked, edits=[])
        path = self._path or "demo-app/app/claims/page.tsx"
        return schema(
            summary="add a status filter to the claims table",
            edits=[{"path": path, "content": "export default function X() { return null; }\n",
                    "reason": "satisfies the criterion"}],
        )
