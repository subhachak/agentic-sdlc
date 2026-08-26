"""Framework routing conventions: which file serves which URL.

Pure path arithmetic, kept in core rather than beside the extractor because
two things need it and they must not disagree. The control plane matches
client calls to route handlers with it; the execution plane attributes what a
test actually requested back to source files with it, via the route map
carried in the graph export.

Nothing here reads a file or executes anything.
"""

from __future__ import annotations

import posixpath
import re

WILDCARD = "*"

_PAGE_FILES = ("page.tsx", "page.ts", "page.jsx", "page.js")
_LAYOUT_FILES = ("layout.tsx", "layout.ts", "layout.jsx", "layout.js")
_HANDLER_FILES = ("route.ts", "route.tsx", "route.js", "route.jsx")


def normalise_route(raw: str) -> str:
    """One shape for a route, whichever side declared it.

    `/api/runs/{run_id}`, `/api/runs/[id]` and `/api/runs/${runId}` are the
    same endpoint written three ways, so each dynamic segment collapses to a
    single wildcard before anything is compared.
    """
    path = raw.strip()
    # Drop an origin: a protocol, or a template variable standing in for one.
    path = re.sub(r"^\$\{[^}]*\}", "", path)
    path = re.sub(r"^[a-zA-Z]+://[^/]*", "", path)
    path = path.split("?", 1)[0].split("#", 1)[0]
    if not path.startswith("/"):
        path = "/" + path
    path = posixpath.normpath(path)

    segments = []
    for segment in path.split("/"):
        if not segment:
            continue
        if (
            segment.startswith("${")
            or (segment.startswith("[") and segment.endswith("]"))
            or (segment.startswith("{") and segment.endswith("}"))
            or "${" in segment
        ):
            segments.append(WILDCARD)
        else:
            segments.append(segment)
    return "/" + "/".join(segments)


def routes_match(declared: str, called: str) -> bool:
    """Segment-wise, with wildcards matching anything.

    Deliberately not a prefix match: `/api/runs` and `/api/runs/{id}` are
    different endpoints handled by different functions, and treating one as
    the other manufactures edges.
    """
    left = [s for s in declared.split("/") if s]
    right = [s for s in called.split("/") if s]
    if len(left) != len(right):
        return False
    return all(
        a == b or a == WILDCARD or b == WILDCARD for a, b in zip(left, right)
    )


def handler_route_for(path: str) -> str | None:
    """The URL a Next.js App Router file serves, from where it sits.

    `demo-app/app/api/claims/route.ts` serves `/api/claims`. The package root
    is whatever precedes `app/` (or `src/app/`), so this works the same in a
    monorepo as at a repository root.
    """
    name = path.rsplit("/", 1)[-1]
    if name not in _HANDLER_FILES:
        return None
    segments = path.split("/")[:-1]
    for marker in ("app",):
        if marker in segments:
            index = len(segments) - 1 - segments[::-1].index(marker)
            return normalise_route("/" + "/".join(segments[index + 1:]))
    return None


def page_route_for(path: str) -> str | None:
    """The URL a Next.js page file serves.

    The mirror of `_next_route_for` for pages rather than handlers. Needed
    because coverage is observed from what a test actually requested, and a
    navigation to `/claims` has to be attributable back to the file that
    served it.
    """
    name = path.rsplit("/", 1)[-1]
    if name not in _PAGE_FILES:
        return None
    segments = path.split("/")[:-1]
    if "app" not in segments:
        return None
    # The *first* `app` segment is the router root. Taking the last one
    # breaks the moment a route is itself named `app`: in Fronei,
    # apps/web/app/app/page.tsx serves /app, and reading from the last
    # match made it serve / — colliding with the real root page, so a
    # request to /app was credited to the file serving / and the workbench
    # route was attributable to nothing.
    #
    # Safe in the other direction because the check is exact: `apps` is not
    # `app`, so a repository rooted at apps/web is unaffected.
    index = segments.index("app")
    return normalise_route("/" + "/".join(segments[index + 1:]))


def route_map(paths: list[str]) -> dict[str, list[str]]:
    """URL to the files that serve it, including the layouts above it.

    Layouts are included because they genuinely execute on every navigation
    beneath them — a request for `/claims` runs `app/layout.tsx` as surely as
    it runs `app/claims/page.tsx`. Leaving them out would report a file as
    untested that every single page test exercises.
    """
    layouts: dict[str, list[str]] = {}
    for path in paths:
        if path.rsplit("/", 1)[-1] in _LAYOUT_FILES:
            layouts.setdefault(posixpath.dirname(path), []).append(path)

    out: dict[str, list[str]] = {}
    for path in paths:
        page_route = page_route_for(path)
        route = page_route or handler_route_for(path)
        if route is None:
            continue
        directory = posixpath.dirname(path)
        # Layouts wrap pages, not route handlers. A request to /api/claims
        # runs no layout, and crediting one would report a file as exercised
        # by a test that never rendered anything.
        applicable = [
            file
            for parent, files in layouts.items()
            if page_route and (directory == parent or directory.startswith(f"{parent}/"))
            for file in files
        ]
        out.setdefault(route, [])
        for file in [path, *applicable]:
            if file not in out[route]:
                out[route].append(file)
    return {route: sorted(files) for route, files in sorted(out.items())}


