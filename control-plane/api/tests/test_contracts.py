"""HTTP coupling: which file calls which route handler.

The structural blind spot in an import graph. A frontend and the API it
calls import nothing from one another, so on imports alone a change to a
route handler reports an impact set containing none of its callers —
measured on one repository, zero edges between the web and api packages
while five web files called the API.
"""

from __future__ import annotations

from app.adapters.code_intelligence.contracts import (
    contract_edges,
    called_routes,
    declared_routes,
)
from app.core.routing import normalise_route, page_route_for, route_map, routes_match


# --- normalising -----------------------------------------------------------


def test_the_same_endpoint_written_three_ways_normalises_to_one_shape():
    """FastAPI, Next.js and a template literal each spell a dynamic segment
    differently. Unless they reduce to the same thing, nothing matches."""
    assert normalise_route("/api/runs/{run_id}") == "/api/runs/*"
    assert normalise_route("/api/runs/[id]") == "/api/runs/*"
    assert normalise_route("/api/runs/${runId}") == "/api/runs/*"


def test_an_origin_and_a_query_string_are_stripped():
    assert normalise_route("${API_URL}/api/runs?limit=5") == "/api/runs"
    assert normalise_route("https://example.com/api/runs") == "/api/runs"


def test_a_prefix_is_not_a_match():
    """`/api/runs` and `/api/runs/{id}` are different endpoints handled by
    different functions. Treating one as the other manufactures edges."""
    assert routes_match("/api/runs", "/api/runs") is True
    assert routes_match("/api/runs/*", "/api/runs/abc") is True
    assert routes_match("/api/runs", "/api/runs/abc") is False


# --- server side -----------------------------------------------------------


def test_a_next_route_file_declares_the_url_its_directory_names():
    sources = {
        "demo-app/app/api/claims/route.ts": "export async function GET() {}",
    }
    declared = declared_routes(sources)

    assert [(d.path, d.method, d.framework) for d in declared] == [
        ("/api/claims", "GET", "next")
    ]


def test_a_next_route_in_a_dynamic_directory_becomes_a_wildcard():
    sources = {"web/src/app/api/runs/[id]/route.ts": "export async function GET() {}"}
    assert declared_routes(sources)[0].path == "/api/runs/*"


def test_a_fastapi_route_combines_mount_prefix_router_prefix_and_decorator():
    """All three are needed. `/runs` on the router plus `/api` at the mount
    plus `/{run_id}` on the decorator is what a browser actually calls, and
    any one of them alone matches nothing."""
    sources = {
        "api/app/main.py": 'app.include_router(runs.router, prefix="/api")',
        "api/app/routers/runs.py": (
            'router = APIRouter(prefix="/runs", tags=["runs"])\n'
            '@router.get("/{run_id}")\n'
            "def get_run(): ...\n"
        ),
    }
    declared = [d for d in declared_routes(sources) if d.framework == "fastapi"]

    assert [(d.path, d.method) for d in declared] == [("/api/runs/*", "GET")]


def test_a_router_imported_under_an_alias_still_finds_its_mount():
    sources = {
        "api/app/main.py": 'app.include_router(graph_router.router, prefix="/api")',
        "api/app/routers/graph.py": (
            'router = APIRouter(prefix="/graph")\n@router.post("/seed")\ndef seed(): ...\n'
        ),
    }
    assert declared_routes(sources)[0].path == "/api/graph/seed"


# --- client side -----------------------------------------------------------


def test_a_template_literal_fetch_is_a_call():
    sources = {"web/api.ts": 'const r = await fetch(`${API_URL}/api/runs`, { cache: "no-store" });'}
    assert [(c.path, c.method) for c in called_routes(sources)] == [("/api/runs", "GET")]


def test_the_method_comes_from_the_options_object():
    sources = {"web/api.ts": 'await fetch(`${API_URL}/api/runs`, { method: "POST", body: f });'}
    assert called_routes(sources)[0].method == "POST"


def test_a_url_assigned_to_a_local_variable_is_still_a_call():
    """demo-app's claims page branches between two query strings before
    calling. One hop inside one file is worth resolving; without it the only
    coupling in the demo app is invisible."""
    sources = {
        "demo-app/page.tsx": (
            'const url = status === "All" ? "/api/claims" : `/api/claims?status=${s}`;\n'
            "fetch(url).then(r => r.json());\n"
        )
    }
    # Both branches of the ternary are extracted; they normalise to the same
    # endpoint, which is the point.
    assert {c.path for c in called_routes(sources)} == {"/api/claims"}


def test_an_event_source_is_a_call_too():
    """A different transport, the same coupling."""
    sources = {"web/view.tsx": 'const es = new EventSource("/api/runs/1/events");'}
    call = called_routes(sources)[0]

    # A literal id stays literal — it is not a dynamic segment. The wildcard
    # lives on the declaration side, and that is what makes them match.
    assert call.path == "/api/runs/1/events"
    assert routes_match("/api/runs/*/events", call.path)


def test_an_external_url_is_not_matched_against_this_repository():
    sources = {"web/api.ts": 'await fetch("https://api.stripe.com/v1/charges");'}
    assert called_routes(sources) == []


# --- matching --------------------------------------------------------------


def test_a_call_and_its_handler_become_an_edge_across_two_services():
    sources = {
        "web/src/lib/api.ts": 'await fetch(`${API_URL}/api/runs/${id}`, { cache: "no-store" });',
        "api/app/main.py": 'app.include_router(runs.router, prefix="/api")',
        "api/app/routers/runs.py": (
            'router = APIRouter(prefix="/runs")\n@router.get("/{run_id}")\ndef g(): ...\n'
        ),
    }
    edges, unmatched, _uncalled = contract_edges(sources)

    assert [(e.source, e.target, e.route) for e in edges] == [
        ("web/src/lib/api.ts", "api/app/routers/runs.py", "/api/runs/*")
    ]
    assert unmatched == []


def test_a_method_that_no_handler_serves_produces_no_edge():
    sources = {
        "web/api.ts": 'await fetch("/api/claims", { method: "DELETE" });',
        "app/api/claims/route.ts": "export async function GET() {}",
    }
    edges, unmatched, _ = contract_edges(sources)

    assert edges == []
    assert [c.method for c in unmatched] == ["DELETE"]


def test_a_url_built_at_runtime_is_counted_as_unseen_rather_than_guessed():
    """The honest limit. A URL assembled from configuration cannot be matched,
    and the count of unmatched calls is what says how much coupling this still
    cannot see."""
    sources = {
        "web/api.ts": "const path = buildPath(resource);\nawait fetch(path);",
        "app/api/claims/route.ts": "export async function GET() {}",
    }
    edges, unmatched, uncalled = contract_edges(sources)

    assert edges == []
    assert unmatched == []          # nothing extractable was extracted
    assert [d.path for d in uncalled] == ["/api/claims"]


def test_a_file_calling_a_route_it_declares_is_not_an_edge_to_itself():
    sources = {
        "app/api/claims/route.ts": (
            "export async function GET() { await fetch('/api/claims'); }"
        )
    }
    edges, _unmatched, _uncalled = contract_edges(sources)
    assert edges == []


# --- route map (used by observed coverage) ---------------------------------


def test_a_page_file_declares_the_url_it_serves():
    assert page_route_for("demo-app/app/claims/page.tsx") == "/claims"
    assert page_route_for("demo-app/app/page.tsx") == "/"
    assert page_route_for("demo-app/app/api/claims/route.ts") is None


def test_a_layout_counts_as_serving_every_page_beneath_it():
    """It genuinely executes on every navigation under it. Leaving it out
    would report a file as untested that every page test exercises."""
    mapping = route_map([
        "demo-app/app/layout.tsx",
        "demo-app/app/page.tsx",
        "demo-app/app/claims/page.tsx",
    ])

    assert mapping["/claims"] == ["demo-app/app/claims/page.tsx", "demo-app/app/layout.tsx"]
    assert mapping["/"] == ["demo-app/app/layout.tsx", "demo-app/app/page.tsx"]


def test_a_layout_does_not_count_as_serving_an_api_route():
    """A request to /api/claims runs no layout. Crediting one would report a
    file as exercised by a test that never rendered anything."""
    mapping = route_map([
        "demo-app/app/layout.tsx",
        "demo-app/app/api/claims/route.ts",
    ])

    assert mapping["/api/claims"] == ["demo-app/app/api/claims/route.ts"]


def test_a_route_named_app_is_not_mistaken_for_the_router_root():
    """`apps/web/app/app/page.tsx` serves /app, not /.

    The router root was found by scanning backwards for a segment named
    `app`, so a route that is itself called `app` shadowed it — the file
    serving /app resolved to / and collided with the real root page. A
    request to /app was then credited to the wrong file, and the route the
    workbench lives on was attributable to nothing at all.

    Found by pointing the platform at a real repository; demo-app has no
    route named `app`, so nothing here could have shown it.
    """
    from app.core.routing import page_route_for

    assert page_route_for("apps/web/app/app/page.tsx") == "/app"
    assert page_route_for("apps/web/app/page.tsx") == "/"
    # And the two no longer claim the same URL.
    assert page_route_for("apps/web/app/app/page.tsx") != page_route_for(
        "apps/web/app/page.tsx"
    )


def test_a_repository_rooted_at_apps_is_unaffected():
    """The match is exact, so `apps` is never taken for `app`."""
    from app.core.routing import page_route_for

    assert page_route_for("apps/web/app/admin/page.tsx") == "/admin"
    assert page_route_for("demo-app/app/claims/page.tsx") == "/claims"
