"""The task statement handed to an agent this platform does not run.

An in-process agent is given a schema and refused if it returns something
else. A client's cloud agent is given prose and does what it likes, so the
statement has to carry the constraints as text and the review afterwards has
to assume none of them were honoured.

Kept apart from `agents/implementation.py` because it is a different genre of
writing: that one prompts a model whose output shape is enforced, this one
briefs a contractor whose output is a pull request.
"""

from __future__ import annotations

from typing import Any


def build_task(
    *,
    requirement: str,
    design: dict[str, Any],
    criteria: list[dict[str, Any]],
    run_id: str,
) -> str:
    modules = [m for m in design.get("modules") or [] if m]
    files = [f for f in design.get("files") or [] if f]
    addressed = set(design.get("criteria_addressed") or [])
    relevant = [c for c in criteria if c.get("id") in addressed] or criteria

    file_lines = [f"  {path}" for path in files] or ["  (the design named no files)"]
    module_lines = [f"  {module}" for module in modules] or [
        "  (the design named no modules)"
    ]

    criteria_text = (
        "\n".join(f"  {c.get('id', '?')}: {c.get('text', '')}" for c in relevant)
        or "  (none recorded)"
    )

    return "\n".join(
        [
            requirement.strip() or "(no requirement text was recorded)",
            "",
            "## Acceptance criteria",
            criteria_text,
            "",
            "## Design already approved",
            design.get("rationale", "").strip() or design.get("summary", "").strip(),
            "",
            "## Scope",
            "Change only these files:",
            *file_lines,
            "",
            "They belong to these modules, and nothing outside them may be edited:",
            *module_lines,
            "",
            # Stated because it is true and because it changes what a competent
            # agent does with an ambiguous instruction: widening scope to be
            # helpful is the specific behaviour that will get the work refused.
            "This scope was approved by a human against a dependency graph of "
            "the repository. A change touching anything outside it is refused "
            "automatically after you finish — the branch is checked against "
            "this list before it goes anywhere. If the work cannot be done "
            "within these files, say so in the pull request description and "
            "change nothing rather than widening the scope.",
            "",
            "Do not modify CI workflows, secrets, or dependency manifests.",
            "",
            f"Raised by the agentic SDLC pipeline, run {run_id}.",
        ]
    )
