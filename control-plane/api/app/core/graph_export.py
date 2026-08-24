"""Export the derived graph in the form the execution plane can consume.

Two planes, one graph. The execution plane runs in client CI with no route
to the control plane's database, so it cannot query the graph — which is why
it held its own copy, hand-authored, module-level, and free to disagree with
the derived one. The disagreement was not hypothetical: every coverage claim
in that file named a script that did not exist, and its paths were relative
to a directory the other plane never used.

A generated export is the mechanism that removes the second source of truth
without pretending the two processes can share a database. It carries the
provenance stamp, so a consumer can refuse a graph that describes a commit it
is not testing, and it is scoped to the part of the repository the consumer
cares about.

What it deliberately does *not* carry is coverage. Which script covers which
module is a property of the scripts, so it belongs in their manifest — the
old file asserted it here, which is how a module came to claim coverage from
a script nobody had written.
"""

from __future__ import annotations

from typing import Any

from app.core.routing import route_map
from app.graph.projects import DEFAULT_PROJECT

EXPORT_VERSION = 2


def _in_scope(path: str, scope: str) -> bool:
    return not scope or path == scope or path.startswith(f"{scope.rstrip('/')}/")


async def build_export(
    graph: Any, scope: str = "", project: str = DEFAULT_PROJECT
) -> dict[str, Any]:
    """The derived graph as JSON, optionally narrowed to a subtree.

    Scoping matters for more than size: a QA run testing `demo-app/` should
    not be told that a change reaches the control plane's own modules, which
    it neither deploys nor tests.
    """
    provenance = await graph.index_provenance(project)
    module_paths = await graph.module_paths(project)
    file_deps = await graph.file_dependents(project, include_tests=False)

    modules = {
        module: sorted(p for p in paths if _in_scope(p, scope))
        for module, paths in module_paths.items()
    }
    modules = {m: paths for m, paths in modules.items() if paths}

    path_to_module = {p: m for m, paths in modules.items() for p in paths}

    # Module dependencies are re-derived from the file edges rather than read
    # from DEPENDS_ON, so the export cannot disagree with the file-level truth
    # it was rolled up from.
    depends_on: dict[tuple[str, str], int] = {}
    for target, sources in file_deps.items():
        target_module = path_to_module.get(target)
        if target_module is None:
            continue
        for source in sources:
            source_module = path_to_module.get(source)
            if source_module and source_module != target_module:
                key = (source_module, target_module)
                depends_on[key] = depends_on.get(key, 0) + 1

    return {
        "export_version": EXPORT_VERSION,
        "project": project,
        # URL to the files that serve it. Carried so the execution plane can
        # attribute what a test actually requested back to source files
        # without re-implementing the framework's routing conventions — the
        # kind of duplication that lets the two planes drift.
        "routes": route_map(sorted(path_to_module)),
        "generated": True,
        "scope": scope,
        "provenance": provenance,
        "modules": [
            {"id": module, "paths": paths} for module, paths in sorted(modules.items())
        ],
        "depends_on": [
            {"from": source, "to": target, "weight": weight}
            for (source, target), weight in sorted(depends_on.items())
        ],
        "file_dependents": {
            target: sorted(s for s in sources if _in_scope(s, scope))
            for target, sources in sorted(file_deps.items())
            if _in_scope(target, scope)
            and any(_in_scope(s, scope) for s in sources)
        },
    }
