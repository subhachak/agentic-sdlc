"""Work out what subtrees of a repository are separately testable.

The export scope used to be a text box defaulted to a name from the sample
app, so pointing the platform at a real repository produced "nothing to
export for scope 'demo-app'" — an error that blamed the index when the index
was fine and the scope matched nothing in it.

A scope is not an arbitrary prefix. It is a deployable unit: the thing a QA
run builds, serves and exercises. Those announce themselves — a manifest at
the root of the subtree is how every ecosystem marks one — so they can be
derived from the index rather than typed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from posixpath import dirname

# A file that marks the root of a separately buildable unit. Deliberately
# manifests only: a Dockerfile or a CI config can sit anywhere, and a README
# marks nothing at all.
MARKERS = frozenset({
    "package.json",       # node
    "pyproject.toml",     # python
    "setup.py",
    "go.mod",             # go
    "Cargo.toml",         # rust
    "pom.xml",            # maven
    "build.gradle",       # gradle
    "build.gradle.kts",
    "Gemfile",            # ruby
    "composer.json",      # php
    "*.csproj",           # dotnet — matched by suffix below
})

_SUFFIX_MARKERS = (".csproj", ".sln")


@dataclass
class ScopeCandidate:
    """One subtree that could be exported on its own."""

    path: str                       # "" means the whole repository
    files: int
    marker: str                     # what identified it
    label: str = ""
    nested: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "path": self.path,
            "files": self.files,
            "marker": self.marker,
            "label": self.label or (self.path or "whole repository"),
            "nested": self.nested,
        }


def _is_marker(filename: str) -> bool:
    return filename in MARKERS or filename.endswith(_SUFFIX_MARKERS)


def is_marker(filename: str) -> bool:
    """Public: the adapters use this while walking, where manifests are still
    visible. By the time the index exists they have been discarded."""
    return _is_marker(filename)


def candidates(
    paths: set[str] | list[str], units: list[str] | None = None
) -> list[ScopeCandidate]:
    """Deployable subtrees found in an index, largest first.

    The whole repository is always offered, and is the only answer when a
    repository has no manifest anywhere — which is a real case (a docs repo,
    a config repo) and not a failure.
    """
    paths = {p for p in paths if p}
    if not paths:
        return []

    roots: dict[str, str] = {}
    # Units come from the indexer, which saw the manifests. Falling back to
    # scanning `paths` is near-useless in practice — manifests are not source
    # and never reach the graph — but it keeps this function honest when
    # called with a raw file list, which the tests do.
    for unit in units or []:
        roots.setdefault(unit.strip("/"), "manifest")
    for path in paths:
        name = path.rsplit("/", 1)[-1]
        if _is_marker(name):
            root = dirname(path)
            # Keep the first marker seen for a directory; which ecosystem
            # claimed it is a label, not a decision.
            roots.setdefault(root, name)

    counts = {root: _count_under(paths, root) for root in roots}

    out: list[ScopeCandidate] = []
    for root, marker in roots.items():
        if not root:
            continue  # the repository root is added below, once
        nested = sorted(r for r in roots if r and r != root and r.startswith(root + "/"))
        out.append(ScopeCandidate(path=root, files=counts[root], marker=marker, nested=nested))

    out.sort(key=lambda c: (-c.files, c.path))

    # Always last and always present: someone whose repository is one unit,
    # or whose layout this does not understand, still needs a way through.
    out.append(
        ScopeCandidate(
            path="",
            files=len(paths),
            marker=roots.get("", "") or "none",
            label="whole repository",
        )
    )
    return out


def _count_under(paths: set[str], root: str) -> int:
    if not root:
        return len(paths)
    prefix = root + "/"
    return sum(1 for p in paths if p == root or p.startswith(prefix))


def best(
    paths: set[str] | list[str],
    configured: str | None = None,
    units: list[str] | None = None,
) -> str | None:
    """The scope to use without asking, or None when someone must choose.

    Honours a configured scope when it still matches something — changing a
    repository should not silently retarget an export someone set on purpose.
    Otherwise it answers only when the answer is not a guess: exactly one
    deployable subtree, or none at all.
    """
    found = candidates(paths, units)
    if not found:
        return None

    if configured is not None:
        for candidate in found:
            if candidate.path == configured:
                return configured
        # Configured but matching nothing: fall through and propose, rather
        # than export an empty graph the QA plane would trust.

    real = [c for c in found if c.path]
    if len(real) == 1:
        return real[0].path
    if not real:
        return ""
    return None


def describe(
    paths: set[str] | list[str],
    configured: str | None = None,
    units: list[str] | None = None,
) -> dict:
    """Everything the console needs to render the choice."""
    found = candidates(paths, units)
    chosen = best(paths, configured, units)
    return {
        "candidates": [c.as_dict() for c in found],
        "selected": chosen,
        "must_choose": chosen is None,
        "configured": configured,
        "configured_matches": configured is not None
        and any(c.path == configured for c in found),
    }
