"""Routes read from the framework, not guessed from directory names.

`page_route_for` derives a URL from a Next.js file path by convention. It is
correct for the plain case and wrong for most of the rest, and the wrongness
is silent — the route simply matches nothing a test ever requested, so
coverage is attributed to a URL nobody visits and the file reads as
unexercised.

Measured against the App Router constructs a real application uses,
inference was wrong on five of six. Fronei happens to use none of them, which
is exactly why this went unnoticed: the codebase that would have caught it
was the next one.

Next writes the answer to .next/app-path-routes-manifest.json during any
build. The route table is the framework's to define, and re-deriving it is
reimplementing route groups, parallel routes, intercepting routes and
private folders correctly or being quietly wrong.
"""

from __future__ import annotations

import json

from app.core.graph_export import read_route_manifest
from app.core.routing import page_route_for, route_map, routes_from_manifest


# What Next actually writes: keys are app-relative and extensionless and keep
# the group or slot; values are the URLs served.
MANIFEST = {
    "/admin/page": "/admin",
    "/app/page": "/app",
    "/(marketing)/pricing/page": "/pricing",
    "/blog/[slug]/page": "/blog/[slug]",
}

PATHS = [
    "apps/web/app/admin/page.tsx",
    "apps/web/app/app/page.tsx",
    "apps/web/app/(marketing)/pricing/page.tsx",
    "apps/web/app/_internal/page.tsx",
]


def test_a_route_group_is_not_a_url_segment():
    """Parentheses organise the directory tree and never appear in the URL.
    Inference read /(marketing)/pricing, which matches no request ever made."""
    assert page_route_for("apps/web/app/(marketing)/pricing/page.tsx") == "/(marketing)/pricing"
    assert routes_from_manifest(MANIFEST, PATHS)["apps/web/app/(marketing)/pricing/page.tsx"] == "/pricing"


def test_a_private_folder_serves_nothing():
    """An underscore excludes a directory from routing entirely. Inference
    invented /_internal; the manifest simply does not list it, and absence is
    the correct answer rather than a lookup failure."""
    assert page_route_for("apps/web/app/_internal/page.tsx") == "/_internal"
    assert "apps/web/app/_internal/page.tsx" not in routes_from_manifest(MANIFEST, PATHS)


def test_the_plain_cases_still_agree():
    """The manifest is not a rewrite of the conventions, it is the authority
    on them. Where inference was right it stays right."""
    out = routes_from_manifest(MANIFEST, PATHS)
    assert out["apps/web/app/admin/page.tsx"] == "/admin"
    # And the first-`app` rule survives: a route named `app` is not the root.
    assert out["apps/web/app/app/page.tsx"] == "/app"


def test_dynamic_segments_are_normalised_to_this_platforms_notation():
    """The manifest says /blog/[slug]; routes_match compares wildcards."""
    out = routes_from_manifest({"/blog/[slug]/page": "/blog/[slug]"},
                               ["apps/web/app/blog/[slug]/page.tsx"])
    assert out["apps/web/app/blog/[slug]/page.tsx"] == "/blog/*"


def test_inference_remains_the_fallback_rather_than_the_default():
    """`.next/` is build output — gitignored, absent from a fresh clone, and
    excluded from the index. Missing is a normal state, not an error."""
    out = route_map(["apps/web/app/admin/page.tsx"], manifest=None)
    assert out["/admin"] == ["apps/web/app/admin/page.tsx"]


def test_a_missing_or_unreadable_manifest_is_not_a_failure(tmp_path):
    assert read_route_manifest(tmp_path) == {}
    broken = tmp_path / ".next"
    broken.mkdir()
    (broken / "app-path-routes-manifest.json").write_text("{ not json")
    assert read_route_manifest(tmp_path) == {}


def test_a_real_manifest_is_read_from_the_working_copy(tmp_path):
    target = tmp_path / "apps" / "web" / ".next"
    target.mkdir(parents=True)
    (target / "app-path-routes-manifest.json").write_text(json.dumps(MANIFEST))
    assert read_route_manifest(tmp_path, "apps/web")["/admin/page"] == "/admin"
