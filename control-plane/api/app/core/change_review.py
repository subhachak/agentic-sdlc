"""Deterministic review of a proposed code change.

The implementation agent writes the patch; this decides whether it may be
proposed at all. No model is involved, for the same reason no model is
involved in the QA gate: an agent must never be the thing that approves its
own work.

The containment check is what the context graph was built for. A design
decision names the components it affects; a change that edits a component
outside that set is doing something nobody agreed to, and that is knowable
before a line of it runs.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field

MAX_FILES = 25
MAX_BYTES_PER_FILE = 120_000

# Anything the pipeline should never be writing on its own initiative.
FORBIDDEN_PATHS = (
    ".github/workflows/",
    ".git/",
    "node_modules/",
)
FORBIDDEN_SUFFIXES = (".env", ".pem", ".key", "id_rsa")


@dataclass
class ChangeReview:
    allowed: bool
    reasons: list[str] = field(default_factory=list)
    components: list[str] = field(default_factory=list)


def _component_of(path: str, known: dict[str, set[str]]) -> str | None:
    """Which known component owns a path, longest prefix wins."""
    best: str | None = None
    for component, paths in known.items():
        if path in paths and (best is None or len(component) > len(best)):
            best = component
    if best:
        return best
    # A new file has no row in the graph yet; attribute it by directory.
    for component in sorted(known, key=len, reverse=True):
        if path.startswith(f"{component}/"):
            return component
    return None


def review(
    edits: list[dict],
    *,
    allowed_components: list[str] | None = None,
    known_components: dict[str, set[str]] | None = None,
) -> ChangeReview:
    """Decide whether a proposed change may be opened.

    `known_components` maps a component id to the file paths it owns, as the
    context graph has them. `allowed_components` is what the design phase said
    this change would touch.
    """
    reasons: list[str] = []
    touched: set[str] = set()

    if not edits:
        return ChangeReview(False, ["the agent proposed no file changes"])

    if len(edits) > MAX_FILES:
        reasons.append(f"{len(edits)} files changed, more than the {MAX_FILES} allowed")

    for edit in edits:
        path = (edit.get("path") or "").strip()
        content = edit.get("content") or ""

        if not path:
            reasons.append("an edit has no path")
            continue
        if path.startswith("/") or ".." in path.split("/"):
            reasons.append(f"{path}: escapes the repository")
            continue
        if any(path.startswith(prefix) for prefix in FORBIDDEN_PATHS) or path.endswith(
            FORBIDDEN_SUFFIXES
        ):
            reasons.append(f"{path}: the pipeline does not edit this")
            continue
        if len(content.encode()) > MAX_BYTES_PER_FILE:
            reasons.append(f"{path}: larger than {MAX_BYTES_PER_FILE} bytes")
            continue

        # Syntax is checkable for Python without executing anything. It is not
        # for TypeScript without a parser, so that is left to the build, which
        # is where an unparseable file would fail anyway.
        if path.endswith(".py"):
            try:
                ast.parse(content)
            except SyntaxError as exc:
                reasons.append(f"{path}: does not parse ({exc.msg} at line {exc.lineno})")
                continue

        if known_components:
            component = _component_of(path, known_components)
            if component:
                touched.add(component)

    if allowed_components and touched:
        outside = sorted(touched - set(allowed_components))
        if outside:
            reasons.append(
                "changes components the design did not name: " + ", ".join(outside)
            )

    return ChangeReview(not reasons, reasons, sorted(touched))
