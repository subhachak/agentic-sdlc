"""What is populated, and what is not.

First-time setup used to be a single "seed graph" button and an assumption.
Everything downstream depends on the graph being hydrated — design grounding,
containment, impact, the QA plane's scoping — and each of those degrades
differently when it is not: an empty graph refuses, a stale one answers
confidently about the wrong commit, an unbuilt retrieval index grounds an
agent in nothing without saying so.

This reports each of them separately, because "is it set up" has more than
one answer and the useful thing is which part is missing.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

# Order matters: each step depends on the one before it, so the console can
# present them as a sequence and disable what is not yet possible.
STEP_INDEX = "index"
STEP_RETRIEVAL = "retrieval"
STEP_EXPORT = "export"


async def status(graph: Any, retrieval: Any, export_path: Path | None) -> dict[str, Any]:
    counts = await graph.counts()
    provenance = await graph.index_provenance()
    nodes = counts.get("nodes", {})
    edges = counts.get("edges", {})

    indexed = bool(nodes.get("MODULE"))
    steps = [
        {
            "id": STEP_INDEX,
            "title": "Index the repository",
            "detail": (
                f"{nodes.get('MODULE', 0)} modules, {nodes.get('SOURCE_ARTIFACT', 0)} files, "
                f"{edges.get('IMPORTS', 0)} import edges, "
                f"{edges.get('CALLS_ENDPOINT', 0)} HTTP edges"
                if indexed
                else "nothing indexed yet — every gate downstream refuses until this runs"
            ),
            "ready": indexed,
            "blocked_by": None,
            "quality": _quality(provenance),
        }
    ]

    retrieval_status = await _retrieval_status(retrieval)
    steps.append(
        {
            "id": STEP_RETRIEVAL,
            "title": "Build the retrieval index",
            "detail": (
                f"{retrieval_status.get('chunks', 0)} chunks"
                + (" — stale, rebuilt on next query" if retrieval_status.get("stale") else "")
                if retrieval_status.get("built")
                else "not built — the design agent is grounded in nothing until it is"
            ),
            "ready": bool(retrieval_status.get("built")) and not retrieval_status.get("stale"),
            "blocked_by": None if indexed else STEP_INDEX,
            "quality": None,
        }
    )

    export = _export_status(export_path, provenance.get("commit_sha"))
    steps.append(
        {
            "id": STEP_EXPORT,
            "title": "Export for the execution plane",
            "detail": export["detail"],
            "ready": export["current"],
            "blocked_by": None if indexed else STEP_INDEX,
            "quality": None,
        }
    )

    return {
        "hydrated": all(step["ready"] for step in steps),
        "provenance": provenance,
        "counts": counts,
        "steps": steps,
    }


def _quality(provenance: dict[str, Any]) -> dict[str, Any] | None:
    capture = provenance.get("internal_capture_rate")
    if capture is None:
        return None
    return {
        "internal_capture_rate": capture,
        # Matches design_review.MIN_CAPTURE_RATE. Below it the design phase
        # refuses outright, so the console should say so before someone
        # starts a run and watches it decline.
        "sufficient": capture >= 0.80,
        "most_missed": (provenance.get("most_missed") or [])[:5],
    }


async def _retrieval_status(retrieval: Any) -> dict[str, Any]:
    reporter = getattr(retrieval, "status", None)
    if reporter is None:
        # The fixture adapter has nothing to build and nothing to be stale.
        return {"built": True, "chunks": 0, "stale": False, "fixed": True}
    return await reporter()


def _export_status(export_path: Path | None, commit: str | None) -> dict[str, Any]:
    if export_path is None:
        return {"current": False, "detail": "no export path configured"}
    if not export_path.exists():
        return {
            "current": False,
            "detail": f"{export_path.name} has not been written — the QA plane has no graph",
        }

    import json

    try:
        payload = json.loads(export_path.read_text())
    except (OSError, json.JSONDecodeError):
        return {"current": False, "detail": f"{export_path.name} is unreadable"}

    exported = (payload.get("provenance") or {}).get("commit_sha")
    if not payload.get("generated"):
        return {"current": False, "detail": "the file on disk was not generated from an index"}
    if commit and exported != commit:
        return {
            "current": False,
            "detail": (
                f"exported {(exported or '?')[:7]}, graph now holds {commit[:7]} — "
                f"the QA plane would scope against the wrong commit"
            ),
        }
    return {
        "current": True,
        "detail": f"{len(payload.get('modules') or [])} modules at {(exported or '?')[:7]}",
    }
