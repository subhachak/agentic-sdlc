"""What each test actually exercised, read from the run rather than declared.

`covers_modules` in the manifest is a claim a person typed. It is better than
the graph asserting it, and it is still an assertion: nothing checks that the
script named there touches the module it names, and nothing notices when a
script drifts away from what it once covered.

This reads the other direction. Playwright already records a trace per test
— for evidence, and `trace: "on"` is already configured — and that trace
contains every request the test made: navigations, `request` fixture calls,
and routes it intercepted. Mapping those URLs back through the route map the
graph export carries gives the set of source files the test demonstrably
exercised.

Route-level, not statement-level, and worth being precise about the
difference. It cannot tell you which branch of a handler ran. It can tell you
that a test which claims to cover the claims API never once requested it,
which is the failure mode a hand-written mapping cannot detect at all.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from orchestrator.context import _load_code_graph

# Framework and tooling requests. A test does not "cover" the Next.js runtime
# by loading its chunks, and counting them would credit every navigation with
# exercising everything.
_IGNORED_PREFIXES = ("/_next/", "/__next", "/favicon")


def request_paths(trace_zip: Path) -> set[tuple[str, str]]:
    """Every (method, path) a test issued, from its trace.

    The trace's `.network` entries are HAR-shaped, which is a documented
    format rather than an internal one — the reason this is read post-hoc
    instead of instrumenting the specs. A spec may only import
    `@playwright/test`, so there is nowhere to hang a fixture without
    weakening the sandbox rule that keeps generated code contained.
    """
    out: set[tuple[str, str]] = set()
    if not trace_zip.exists():
        return out

    try:
        with zipfile.ZipFile(trace_zip) as archive:
            for name in archive.namelist():
                if not name.endswith(".network"):
                    continue
                for line in archive.read(name).decode("utf-8", "replace").splitlines():
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    request = (event.get("snapshot") or {}).get("request") or {}
                    url = request.get("url")
                    if not url:
                        continue
                    path = urlsplit(url).path or "/"
                    if path.startswith(_IGNORED_PREFIXES):
                        continue
                    out.add((request.get("method", "GET").upper(), path))
    except (zipfile.BadZipFile, KeyError):
        return out
    return out


def _routes() -> dict[str, list[str]]:
    return _load_code_graph().get("routes") or {}


def _segments(path: str) -> list[str]:
    return [s for s in path.split("/") if s]


def files_for_path(path: str, routes: dict[str, list[str]] | None = None) -> list[str]:
    """Which source files serve a requested path.

    Matched segment-wise so a dynamic route matches a concrete request:
    `/api/runs/*` serves `/api/runs/abc`. An exact match wins over a wildcard
    one, because two routes can both match and only the specific one is the
    file that actually ran.
    """
    routes = _routes() if routes is None else routes
    if path in routes:
        return list(routes[path])

    wanted = _segments(path)
    for declared, files in sorted(routes.items(), key=lambda kv: -kv[0].count("*")):
        pattern = _segments(declared)
        if len(pattern) != len(wanted):
            continue
        if all(a == b or a == "*" for a, b in zip(pattern, wanted)):
            return list(files)
    return []


def observed_files(paths: set[tuple[str, str]], routes: dict[str, list[str]] | None = None) -> set[str]:
    routes = _routes() if routes is None else routes
    return {f for _method, path in paths for f in files_for_path(path, routes)}


def observed_modules(files: set[str]) -> set[str]:
    graph = _load_code_graph()
    return {
        module["id"]
        for module in graph.get("modules", [])
        if set(module.get("paths") or []) & files
    }


def reachable_files(routes: dict[str, list[str]] | None = None) -> set[str]:
    """Every file any route can reach.

    The denominator. A file the framework never serves — a config, a type
    declaration — cannot be exercised by a browser test and counting it as
    uncovered would make the number meaningless.
    """
    routes = _routes() if routes is None else routes
    return {f for files in routes.values() for f in files}


def coverage_gaps(observed: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """What a run left untouched, at file level rather than module level.

    Module granularity hides this. `demo-app/app` holds both `layout.tsx` and
    `page.tsx`; every page test runs the layout, so the module reads as
    covered while the home page has never been visited. The file list is the
    honest unit and the module list is the one the blast radius scopes on, so
    both are reported.
    """
    seen = {f for entry in observed.values() for f in entry.get("files", [])}
    requested = {
        request.split(" ", 1)[-1]
        for entry in observed.values()
        for request in entry.get("requests", [])
    }
    reachable = reachable_files()
    missed = sorted(reachable - seen)
    return {
        "files_reached": sorted(seen & reachable),
        "files_never_reached": missed,
        "reachable_total": len(reachable),
        "file_coverage": round(len(seen & reachable) / len(reachable), 4) if reachable else 1.0,
        # Compared against what was actually requested, not against which
        # files were reached: `/` and `/claims` share a layout, so a route
        # nobody visited looks visited the moment any sibling page is.
        "routes_never_requested": sorted(
            route
            for route in (_routes() or {})
            if not any(_matches(route, path) for path in requested)
        ),
    }


def _matches(declared: str, requested: str) -> bool:
    pattern, wanted = _segments(declared), _segments(requested)
    if len(pattern) != len(wanted):
        return False
    return all(a == b or a == "*" for a, b in zip(pattern, wanted))


def coverage_for_trace(trace_zip: Path) -> dict[str, Any]:
    """One test's observed coverage: what it requested, and what that ran."""
    paths = request_paths(trace_zip)
    files = observed_files(paths)
    return {
        "requests": sorted(f"{method} {path}" for method, path in paths),
        "files": sorted(files),
        "modules": sorted(observed_modules(files)),
    }


def _walk_specs(node: Any, file: str = ""):
    """Every (spec_file, status, trace_path) leaf in a Playwright report."""
    if not isinstance(node, dict):
        return
    file = node.get("file") or file
    for spec in node.get("specs", []):
        spec_file = spec.get("file") or file
        for test in spec.get("tests", []):
            for result in test.get("results", []) or [{}]:
                traces = [
                    a.get("path")
                    for a in result.get("attachments", []) or []
                    if a.get("name") == "trace" and a.get("path")
                ]
                yield spec_file, result.get("status", test.get("status", "unknown")), traces
    for child in node.get("suites", []):
        yield from _walk_specs(child, file)


def coverage_by_spec(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Observed coverage per spec file, unioned across its tests.

    Keyed by spec filename because that is what an assignment records — a
    title cannot identify which spec produced a result, and coverage credited
    to the wrong spec is worse than none.
    """
    out: dict[str, dict[str, Any]] = {}
    for spec_file, status, traces in _walk_specs(report):
        name = (spec_file or "").replace("\\", "/").rsplit("/", 1)[-1]
        entry = out.setdefault(
            name, {"requests": set(), "files": set(), "modules": set(), "statuses": set()}
        )
        entry["statuses"].add(status)
        for trace in traces:
            paths = request_paths(Path(trace))
            entry["requests"] |= {f"{m} {p}" for m, p in paths}
            entry["files"] |= observed_files(paths)

    for entry in out.values():
        entry["modules"] = observed_modules(entry["files"])

    return {
        name: {
            "requests": sorted(e["requests"]),
            "files": sorted(e["files"]),
            "modules": sorted(e["modules"]),
            "passed": e["statuses"] <= {"expected", "passed"},
        }
        for name, e in sorted(out.items())
    }


def reconcile_declared(observed: dict[str, dict[str, Any]], assignments: list[dict]) -> list[str]:
    """Where the manifest claims coverage the run did not demonstrate.

    The one direction worth failing on. A script covering more than it
    declares is an under-claim and harmless; a script declaring a module it
    never touched is a coverage record that will be trusted by a gate and is
    not true.
    """
    from orchestrator.context import _load_manifest

    by_id = {e["id"]: e for e in _load_manifest()}
    problems: list[str] = []

    for assignment in assignments:
        script_id = assignment.get("source_script_id")
        entry = by_id.get(script_id)
        if not entry:
            continue
        name = (assignment.get("file_path") or "").replace("\\", "/").rsplit("/", 1)[-1]
        seen = observed.get(name)
        if not seen or not seen["passed"]:
            continue  # a failing test is reported elsewhere; it proves nothing here
        unmet = sorted(set(entry.get("covers_modules") or []) - set(seen["modules"]))
        if unmet:
            problems.append(
                f"{script_id} declares coverage of {', '.join(unmet)} but the run "
                f"shows it requested only {', '.join(seen['requests']) or 'nothing'}"
            )
    return problems
