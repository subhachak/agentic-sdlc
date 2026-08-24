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
    def __init__(
        self, files: dict[str, str] | None = None, commit: str | None = "deadbeef"
    ) -> None:
        self.files = files or {"demo-app/app/claims/page.tsx": "export default function X() {}\n"}
        self.opened: list[dict] = []
        # Settable so a test can produce the case where a change was opened
        # but named no commit, which is what the dispatch guard exists for.
        self.commit = commit

    async def read_files(self, repo, ref, paths):
        return {p: self.files[p] for p in paths if p in self.files}

    async def open_change(self, repo, base_ref, branch, title, body, edits):
        self.opened.append({"branch": branch, "title": title,
                            "files": [e.path for e in edits]})
        return ChangeRef(
            provider="stub", branch=branch, url=f"https://stub/pull/{len(self.opened)}",
            number=len(self.opened), commit=self.commit, base_commit="cafe0000",
            files=[e.path for e in edits],
        )


class WritingLLMProvider:
    """Returns one edit to the first file it was shown."""

    def __init__(
        self,
        *,
        blocked: str = "",
        path: str | None = None,
        modules: list[str] | None = None,
        criteria: list[str] | None = None,
        implementation_path: str | None = None,
    ) -> None:
        self._blocked = blocked
        self._path = path
        self._components = modules or ["demo-app/app/claims"]
        self._criteria = criteria or []
        # Lets a test make the two phases disagree. Containment only means
        # anything when the implementation writes somewhere the design did not
        # name, and a double that always agrees with itself cannot produce
        # that case.
        self._implementation_path = implementation_path

    async def complete(self, system_prompt, user_prompt, *, max_tokens=1024):
        return LLMResponse(text="[stub]", model="stub", input_tokens=1, output_tokens=1)

    async def complete_json(self, system_prompt, user_prompt, schema, *, max_tokens=16000):
        # The same double serves the design and implementation phases; which
        # one is asking is evident from the schema it wants back.
        if schema.__name__ == "DesignProposal":
            return schema(
                summary="render the table only when there are rows",
                rationale="the criterion is about the claims list, which this module owns",
                modules=self._components,
                files=[self._path or "demo-app/app/claims/page.tsx"],
                criteria_addressed=list(self._criteria),
            )
        if self._blocked:
            return schema(summary="cannot proceed", blocked=self._blocked, edits=[])
        path = self._implementation_path or self._path or "demo-app/app/claims/page.tsx"
        return schema(
            summary="add a status filter to the claims table",
            edits=[{"path": path, "content": "export default function X() { return null; }\n",
                    "reason": "satisfies the criterion"}],
        )
