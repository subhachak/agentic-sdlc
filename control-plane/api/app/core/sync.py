"""One operation that brings everything up to date.

Setting the platform up used to be four buttons and three text boxes that
had to agree with each other: index, then build the retrieval index, then
export, with a repository, a ref and a scope typed into separate fields. The
order was not enforced, the fields did not have to match, and getting one
wrong produced an error that named a different step.

Every part of that is derivable. Whether this is a first index or a delta is
a question about the graph, not the operator. The ref is a property of the
repository. The scope is a property of the code that was just indexed. So
this asks for a repository and works out the rest, reporting each step
separately because "it worked" and "it worked, and nothing had changed" are
different answers.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.core import scoping, seeding
from app.core.graph_export import build_export
from app.graph.projects import DEFAULT_PROJECT

INDEX = "index"
RETRIEVAL = "retrieval"
EXPORT = "export"


def _step(name: str, status: str, summary: str, **extra: Any) -> dict[str, Any]:
    return {"step": name, "status": status, "summary": summary, **extra}


async def sync(
    graph: Any,
    indexer: Any,
    retrieval: Any,
    *,
    repo: str,
    ref: str | None = None,
    scope: str | None = None,
    export_path: Path | None = None,
    project: str = DEFAULT_PROJECT,
    run_id: str = "sync",
    working_copy: str | Path | None = None,
) -> dict[str, Any]:
    """Index or update, ground the design agent, and hand off to the QA plane.

    Never partially silent: a step that could not run says so and why, and
    the steps after it still run when they can. The one thing that stops
    everything is a failed index, because the other two describe it.
    """
    steps: list[dict[str, Any]] = []

    # --- 1. index, or update in place -----------------------------------
    provenance = await graph.index_provenance(project)
    known = provenance.get("repo")
    first_time = not known or known != repo
    ref = ref or provenance.get("ref") or "main"

    if first_time:
        result = await seeding.seed(
            graph, indexer, repo=repo, ref=ref, run_id=run_id, project=project, rebuild=True
        )
        steps.append(_step(
            INDEX, "ok",
            f"Indexed {result['repo']} at {(result.get('commit_sha') or 'unpinned')[:7]}: "
            f"{result['modules']} modules, {result['files']} files.",
            mode="full", detail=result,
        ))
    else:
        result = await seeding.refresh(
            graph, indexer, repo=repo, ref=ref, run_id=run_id, project=project
        )
        delta = result["delta"]
        changed = delta["edges_added"] or delta["edges_removed"]
        steps.append(_step(
            INDEX, "ok",
            (f"Updated to {(result.get('commit_sha') or 'unpinned')[:7]}: "
             f"{delta['edges_added']} edge(s) added, {delta['edges_removed']} removed."
             if changed else
             f"Already current at {(result.get('commit_sha') or 'unpinned')[:7]} — "
             f"{delta['unchanged']} edges unchanged."),
            mode="delta", changed=bool(changed), detail=result,
        ))

    # --- 2. ground the design agent -------------------------------------
    # After the index, always: an index that moved leaves the retrieval
    # index describing a commit that is no longer there, and an agent
    # grounded in a stale snapshot fails silently rather than loudly.
    rebuild = getattr(retrieval, "rebuild", None)
    if rebuild is None:
        steps.append(_step(
            RETRIEVAL, "skipped",
            "the configured grounding adapter has no index to build",
        ))
    else:
        built = await rebuild()
        chunks = built.get("chunks", 0)
        problem = built.get("problem")
        if chunks:
            steps.append(_step(
                RETRIEVAL, "ok", f"Retrieval index built: {chunks} chunks.", detail=built
            ))
        else:
            # Not "ok". An index over nothing answers every design question
            # with nothing, and a tick beside it is how that goes unnoticed
            # until a design phase produces a confidently ungrounded answer.
            steps.append(_step(
                RETRIEVAL, "failed",
                problem or "the retrieval index was built over no files at all",
                detail=built,
            ))

    # --- 3. hand off to the execution plane ------------------------------
    module_paths = await graph.module_paths(project)
    all_paths = {p for paths in module_paths.values() for p in paths}
    # Re-read: the index that just ran is the one that knows where the
    # manifests were.
    units = (await graph.index_provenance(project)).get("units") or []
    choice = scoping.describe(all_paths, scope, units)

    if choice["must_choose"]:
        steps.append(_step(
            EXPORT, "needs_choice",
            "This repository has more than one separately testable subtree. "
            "Choose which one the execution plane should test.",
            **choice,
        ))
    else:
        chosen = choice["selected"] or ""
        export = await build_export(
            graph, scope=chosen, project=project,
            # The one that matters: this is the export the execution
            # plane reads. A route table derived here and a route table
            # the framework built are different facts, and the QA plane
            # attributes coverage with whichever it is handed.
            working_copy=working_copy,
        )
        if not export["modules"]:
            # Should be unreachable: the scope came from the index. Kept
            # because "should be unreachable" has been wrong before, and an
            # empty export is worse than a refusal — the QA plane trusts it.
            steps.append(_step(
                EXPORT, "failed",
                f"scope {chosen!r} matched no files in the index just built",
                **choice,
            ))
        elif export_path is None:
            steps.append(_step(EXPORT, "skipped", "no export path is configured", **choice))
        else:
            export_path.parent.mkdir(parents=True, exist_ok=True)
            import json

            export_path.write_text(json.dumps(export, indent=2) + "\n")
            steps.append(_step(
                EXPORT, "ok",
                f"Exported {len(export['modules'])} modules and "
                f"{len(export.get('routes') or {})} routes"
                + (f" from {chosen}." if chosen else " from the whole repository."),
                scope=chosen, path=str(export_path), **choice,
            ))

    blocking = [s for s in steps if s["status"] in ("failed", "needs_choice")]
    return {
        "ok": not blocking,
        "repo": repo,
        "ref": ref,
        "project": project,
        "first_time": first_time,
        "steps": steps,
    }
