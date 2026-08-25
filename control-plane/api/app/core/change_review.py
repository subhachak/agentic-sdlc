"""Deterministic review of a proposed code change.

The implementation agent writes the patch; this decides whether it may be
proposed at all. No model is involved, for the same reason no model is
involved in the QA gate: an agent must never be the thing that approves its
own work.

The containment check is what the context graph was built for. A design
decision names the modules it affects; a change that edits a module
outside that set is doing something nobody agreed to, and that is knowable
before a line of it runs.

It fails closed in both directions: a path in a module the design did not
name is refused, and so is a path the graph cannot attribute to any module at
all. The second case is the one that matters — an agent writing somewhere
entirely unexpected produces exactly that, and treating "I do not know where
this belongs" as "nothing to check" is how containment gets bypassed.
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
    modules: list[str] = field(default_factory=list)


def _module_of(path: str, known: dict[str, set[str]]) -> str | None:
    """Which known module owns a path, longest prefix wins."""
    best: str | None = None
    for module, paths in known.items():
        if path in paths and (best is None or len(module) > len(best)):
            best = module
    if best:
        return best
    # A new file has no row in the graph yet; attribute it by directory.
    for module in sorted(known, key=len, reverse=True):
        if path.startswith(f"{module}/"):
            return module
    return None


def review(
    edits: list[dict],
    *,
    allowed_modules: list[str] | None = None,
    known_modules: dict[str, set[str]] | None = None,
) -> ChangeReview:
    """Decide whether a proposed change may be opened.

    `known_modules` maps a module id to the file paths it owns, as the
    context graph has them. `allowed_modules` is what the design phase said
    this change would touch.
    """
    reasons: list[str] = []
    touched: set[str] = set()
    unmapped: list[str] = []

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

        if known_modules:
            module = _module_of(path, known_modules)
            if module:
                touched.add(module)
            else:
                unmapped.append(path)

    if allowed_modules:
        outside = sorted(touched - set(allowed_modules))
        if outside:
            reasons.append(
                "changes modules the design did not name: " + ", ".join(outside)
            )
        # A path the graph cannot attribute used to be dropped from `touched`,
        # and the containment check ran only `if touched` — so a change made
        # entirely of unattributable paths skipped the check altogether and
        # was allowed. Containment must fail closed on what it cannot place.
        if unmapped:
            reasons.append(
                "changes files no module in the graph owns, so containment "
                "cannot be checked for them: " + ", ".join(sorted(unmapped))
            )

    return ChangeReview(not reasons, reasons, sorted(touched))
