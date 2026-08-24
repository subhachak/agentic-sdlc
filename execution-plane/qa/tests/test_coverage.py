"""Coverage read from the run rather than declared.

`covers_modules` was a claim a person typed: nothing checked that the script
named there touched the module it named, and nothing noticed when a script
drifted away from what it once covered. These pin the measurement that
replaced it, and the reconciliation that catches a claim the run disproves.
"""

from __future__ import annotations

import json
import zipfile

import pytest

from orchestrator.coverage import (
    coverage_by_spec,
    coverage_gaps,
    files_for_path,
    observed_files,
    reconcile_declared,
    request_paths,
)

ROUTES = {
    "/": ["demo-app/app/layout.tsx", "demo-app/app/page.tsx"],
    "/claims": ["demo-app/app/claims/page.tsx", "demo-app/app/layout.tsx"],
    "/api/claims": ["demo-app/app/api/claims/route.ts"],
    "/api/runs/*": ["demo-app/app/api/runs/[id]/route.ts"],
}


def _trace(tmp_path, *urls: tuple[str, str]):
    """A trace archive shaped like Playwright's, with the network events it
    writes. HAR-shaped, which is why this is read post-hoc: a spec may only
    import @playwright/test, so there is nowhere to hang a fixture without
    weakening the sandbox that keeps generated code contained."""
    path = tmp_path / "trace.zip"
    lines = "\n".join(
        json.dumps({"type": "resource-snapshot",
                    "snapshot": {"request": {"method": m, "url": u}}})
        for m, u in urls
    )
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("0-trace.network", lines)
    return path


# --- reading a trace -------------------------------------------------------


def test_every_request_a_test_made_is_recovered(tmp_path):
    trace = _trace(tmp_path,
                   ("GET", "http://localhost:3000/claims"),
                   ("GET", "http://localhost:3000/api/claims?status=Approved"))

    assert request_paths(trace) == {("GET", "/claims"), ("GET", "/api/claims")}


def test_framework_assets_do_not_count_as_coverage(tmp_path):
    """Loading the Next.js runtime is not exercising the application, and
    counting it would credit every navigation with reaching everything."""
    trace = _trace(tmp_path,
                   ("GET", "http://localhost:3000/claims"),
                   ("GET", "http://localhost:3000/_next/static/chunks/main.js"),
                   ("GET", "http://localhost:3000/favicon.ico"))

    assert request_paths(trace) == {("GET", "/claims")}


def test_a_missing_or_corrupt_trace_yields_nothing_rather_than_failing(tmp_path):
    assert request_paths(tmp_path / "absent.zip") == set()
    broken = tmp_path / "broken.zip"
    broken.write_text("not a zip")
    assert request_paths(broken) == set()


# --- attributing requests to files -----------------------------------------


def test_a_request_is_attributed_to_the_file_that_served_it():
    assert files_for_path("/api/claims", ROUTES) == ["demo-app/app/api/claims/route.ts"]


def test_a_dynamic_route_matches_a_concrete_request():
    assert files_for_path("/api/runs/abc123", ROUTES) == ["demo-app/app/api/runs/[id]/route.ts"]


def test_an_unserved_path_attributes_to_nothing():
    assert files_for_path("/nope", ROUTES) == []


def test_a_navigation_credits_the_layout_that_rendered_it():
    """The layout genuinely executes. Leaving it out reports a file as
    untested that every page test exercises."""
    files = observed_files({("GET", "/claims")}, ROUTES)
    assert files == {"demo-app/app/claims/page.tsx", "demo-app/app/layout.tsx"}


# --- per-spec coverage -----------------------------------------------------


def _report(spec_file: str, trace: str, status: str = "expected") -> dict:
    return {"suites": [{"file": spec_file, "specs": [{
        "title": "t", "file": spec_file,
        "tests": [{"results": [{"status": status,
                                "attachments": [{"name": "trace", "path": trace}]}]}],
    }]}]}


def test_coverage_is_keyed_by_spec_file_not_by_title(tmp_path, monkeypatch):
    """Two scenarios can title their tests identically. Coverage credited to
    the wrong spec is worse than none."""
    import orchestrator.coverage as coverage

    monkeypatch.setattr(coverage, "_routes", lambda: ROUTES)
    monkeypatch.setattr(coverage, "observed_modules", lambda files: {"m"} if files else set())
    trace = _trace(tmp_path, ("GET", "http://localhost:3000/api/claims"))

    result = coverage_by_spec(_report("claims-api.spec.ts", str(trace)))

    assert set(result) == {"claims-api.spec.ts"}
    assert result["claims-api.spec.ts"]["files"] == ["demo-app/app/api/claims/route.ts"]
    assert result["claims-api.spec.ts"]["passed"] is True


def test_a_failing_spec_is_marked_as_such(tmp_path, monkeypatch):
    import orchestrator.coverage as coverage

    monkeypatch.setattr(coverage, "_routes", lambda: ROUTES)
    monkeypatch.setattr(coverage, "observed_modules", lambda files: set())
    trace = _trace(tmp_path, ("GET", "http://localhost:3000/api/claims"))

    result = coverage_by_spec(_report("x.spec.ts", str(trace), status="unexpected"))
    assert result["x.spec.ts"]["passed"] is False


# --- reconciliation --------------------------------------------------------


def test_a_script_claiming_a_module_it_never_touched_is_reported(monkeypatch):
    """The one direction worth failing on. Covering more than you declare is
    harmless; declaring a module you never requested is a coverage record a
    gate will trust and that is not true."""
    monkeypatch.setattr(
        "orchestrator.context._load_manifest",
        lambda: [{"id": "s1", "covers_modules": ["demo-app/app/api/claims"]}],
    )
    observed = {"s1.spec.ts": {"modules": ["demo-app/app/claims"],
                               "requests": ["GET /claims"], "passed": True, "files": []}}
    assignments = [{"source_script_id": "s1", "file_path": "/g/s1.spec.ts"}]

    problems = reconcile_declared(observed, assignments)

    assert len(problems) == 1
    assert "demo-app/app/api/claims" in problems[0]


def test_covering_more_than_declared_is_not_a_problem(monkeypatch):
    monkeypatch.setattr(
        "orchestrator.context._load_manifest",
        lambda: [{"id": "s1", "covers_modules": ["demo-app/app/claims"]}],
    )
    observed = {"s1.spec.ts": {"modules": ["demo-app/app/claims", "demo-app/app"],
                               "requests": ["GET /claims"], "passed": True, "files": []}}

    assert reconcile_declared(observed, [{"source_script_id": "s1",
                                          "file_path": "/g/s1.spec.ts"}]) == []


def test_a_failing_script_proves_nothing_about_coverage(monkeypatch):
    monkeypatch.setattr(
        "orchestrator.context._load_manifest",
        lambda: [{"id": "s1", "covers_modules": ["demo-app/app/api/claims"]}],
    )
    observed = {"s1.spec.ts": {"modules": [], "requests": [], "passed": False, "files": []}}

    assert reconcile_declared(observed, [{"source_script_id": "s1",
                                          "file_path": "/g/s1.spec.ts"}]) == []


# --- gaps ------------------------------------------------------------------


def test_file_level_gaps_are_reported_where_module_level_hides_them(monkeypatch):
    """`demo-app/app` holds both layout.tsx and page.tsx. Every page test runs
    the layout, so the module reads as covered while the home page has never
    been visited."""
    import orchestrator.coverage as coverage

    monkeypatch.setattr(coverage, "_routes", lambda: ROUTES)
    observed = {"a.spec.ts": {"files": ["demo-app/app/claims/page.tsx",
                                        "demo-app/app/layout.tsx"],
                              "requests": ["GET /claims"], "modules": [], "passed": True}}

    gaps = coverage_gaps(observed)

    assert "demo-app/app/page.tsx" in gaps["files_never_reached"]
    assert "/" in gaps["routes_never_requested"]
    assert gaps["file_coverage"] < 1.0


def test_a_route_is_not_counted_as_visited_because_a_sibling_shares_its_layout(monkeypatch):
    import orchestrator.coverage as coverage

    monkeypatch.setattr(coverage, "_routes", lambda: ROUTES)
    observed = {"a.spec.ts": {"files": ["demo-app/app/layout.tsx"],
                              "requests": ["GET /claims"], "modules": [], "passed": True}}

    assert "/" in coverage_gaps(observed)["routes_never_requested"]
