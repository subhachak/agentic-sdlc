"""HTTP coupling: which file calls which route handler.

The structural blind spot in an import graph. A frontend that calls an API
over HTTP produces no import edge to it, so a change to a route handler shows
an impact set that does not include a single one of its callers. Measured on
one repository: zero edges between `apps/web` and `apps/api` while five web
files called the API. This repository has the same shape — one client module
calls twelve endpoints across five router files, and the import graph sees
nothing.

Both halves are statically visible. A server declares a route (a Next.js file
path, a FastAPI decorator) and a client names it in a string literal, so the
edge can be recovered by matching the two. What cannot be recovered this way
is a URL assembled at runtime from configuration — those stay invisible, and
the count of unmatched calls is reported rather than hidden.

Nothing here executes repository content.
"""

from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass

from app.core.routing import WILDCARD, handler_route_for, normalise_route, routes_match

# --- server side -----------------------------------------------------------

# FastAPI: the router's own prefix, the decorator's path, and the prefix the
# application mounts the router under. All three are needed — `/runs` on the
# router plus `/api` at the mount plus `/{run_id}` on the decorator is what
# the browser actually calls.
_PY_ROUTER_PREFIX = re.compile(r"""APIRouter\s*\([^)]*prefix\s*=\s*['"]([^'"]*)['"]""", re.S)
_PY_ROUTE = re.compile(
    r"""@router\.(get|post|put|patch|delete)\s*\(\s*['"]([^'"]*)['"]""", re.I
)
_PY_INCLUDE = re.compile(
    r"""include_router\s*\(\s*([\w.]+)[^)]*?prefix\s*=\s*['"]([^'"]*)['"]""", re.S
)

# Next.js App Router: the route is the directory path, and the file declares
# which methods it serves.
_TS_HANDLER = re.compile(r"""(?m)^\s*export\s+(?:async\s+)?function\s+(GET|POST|PUT|PATCH|DELETE)\b""")

# --- client side -----------------------------------------------------------

_FETCH = re.compile(r"""\bfetch\s*\(\s*(['"`])(.*?)\1""", re.S)
# `fetch(url)` where `url` was assigned a literal a line earlier. Common
# enough to be worth one hop: without it, a page that branches between two
# query strings before calling is invisible, which is exactly what
# demo-app's claims page does.
_FETCH_VARIABLE = re.compile(r"""\bfetch\s*\(\s*([A-Za-z_$][\w$]*)\s*[,)]""")
_LITERAL_ASSIGN = re.compile(r"""['"`](/[^'"`\n]*)['"`]""")
# An EventSource or WebSocket is a route call too — a different transport,
# the same coupling.
_STREAM = re.compile(r"""\bnew\s+(?:EventSource|WebSocket)\s*\(\s*(['"`])(.*?)\1""", re.S)
_AXIOS = re.compile(r"""\baxios\.(get|post|put|patch|delete)\s*\(\s*(['"`])(.*?)\2""", re.I | re.S)
# `method: "POST"` within a few lines of the call, which is how fetch says it.
_METHOD_OPTION = re.compile(r"""method\s*:\s*['"](\w+)['"]""", re.I)


@dataclass(frozen=True)
class RouteDeclaration:
    path: str            # normalised, wildcards for dynamic segments
    method: str          # upper-case, or "" when the file serves several
    file: str
    framework: str


@dataclass(frozen=True)
class RouteCall:
    path: str
    method: str
    file: str
    raw: str


@dataclass(frozen=True)
class ContractEdge:
    source: str          # the file making the call
    target: str          # the file handling the route
    route: str
    method: str
    provenance: str = "static-route-match"


def declared_routes(sources: dict[str, str]) -> list[RouteDeclaration]:
    mounts = _mount_prefixes(sources)
    out: list[RouteDeclaration] = []

    for path, text in sources.items():
        next_route = handler_route_for(path)
        if next_route is not None:
            methods = set(_TS_HANDLER.findall(text)) or {""}
            out.extend(
                RouteDeclaration(next_route, method, path, "next") for method in sorted(methods)
            )
            continue

        if not path.endswith(".py"):
            continue
        router_prefix = (_PY_ROUTER_PREFIX.search(text) or _Empty()).group(1) or ""
        mount = mounts.get(_module_name(path), "")
        for method, route in _PY_ROUTE.findall(text):
            full = normalise_route(f"{mount}{router_prefix}{route}" or "/")
            out.append(RouteDeclaration(full, method.upper(), path, "fastapi"))

    return out


class _Empty:
    def group(self, _index: int) -> str:
        return ""


def _module_name(path: str) -> str:
    return path.rsplit("/", 1)[-1].removesuffix(".py")


def _mount_prefixes(sources: dict[str, str]) -> dict[str, str]:
    """Where each router module is mounted, read from the include_router calls.

    Keyed by module name rather than by path because the application refers to
    a router by however it imported it — `graph_router.router` and
    `graph.router` are the same file under two names.
    """
    out: dict[str, str] = {}
    for text in sources.values():
        for reference, prefix in _PY_INCLUDE.findall(text):
            module = reference.split(".")[0]
            out.setdefault(module, prefix)
    aliases = dict(out)
    for module, prefix in aliases.items():
        out.setdefault(module.removesuffix("_router"), prefix)
    return out


def called_routes(sources: dict[str, str]) -> list[RouteCall]:
    out: list[RouteCall] = []
    for path, text in sources.items():
        if not path.endswith((".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")):
            continue
        for match in _FETCH.finditer(text):
            raw = match.group(2)
            if not _looks_like_a_route(raw):
                continue
            # The method sits in the options object after the URL.
            tail = text[match.end() : match.end() + 200]
            method = (_METHOD_OPTION.search(tail) or _Empty()).group(1) or "GET"
            out.append(RouteCall(normalise_route(raw), method.upper(), path, raw))
        for match in _STREAM.finditer(text):
            raw = match.group(2)
            if _looks_like_a_route(raw):
                out.append(RouteCall(normalise_route(raw), "GET", path, raw))
        for method, _quote, raw in _AXIOS.findall(text):
            if _looks_like_a_route(raw):
                out.append(RouteCall(normalise_route(raw), method.upper(), path, raw))
        out.extend(_calls_through_a_local_variable(path, text))
    return out


def _calls_through_a_local_variable(path: str, text: str) -> list[RouteCall]:
    """`const url = "/api/claims"; fetch(url)`.

    One hop, within one file, and only when the name was assigned a literal
    that looks like a route. Anything further — a URL built from config, or
    passed in as an argument — stays invisible, and is counted as an
    unmatched call rather than guessed at.
    """
    out: list[RouteCall] = []
    for match in _FETCH_VARIABLE.finditer(text):
        name = match.group(1)
        assignment = re.search(
            rf"""\b(?:const|let|var)\s+{re.escape(name)}\s*=([^;\n]*(?:\n[^;\n]*)?)""",
            text[: match.start()],
        )
        if not assignment:
            continue
        for literal in _LITERAL_ASSIGN.findall(assignment.group(1)):
            out.append(RouteCall(normalise_route(literal), "GET", path, literal))
    return out


def _looks_like_a_route(raw: str) -> bool:
    """A URL this repository could plausibly serve.

    A call to a third-party host is a real dependency and not one any file in
    this repository handles, so matching it would only ever produce a false
    edge.
    """
    candidate = raw.strip()
    if not candidate or candidate.startswith("data:"):
        return False
    if re.match(r"^[a-zA-Z]+://", candidate):
        return False  # an absolute external URL
    return candidate.startswith("/") or candidate.startswith("${") or candidate.startswith("`")


def contract_edges(
    sources: dict[str, str],
) -> tuple[list[ContractEdge], list[RouteCall], list[RouteDeclaration]]:
    """Match calls to handlers.

    Returns the edges, the calls nothing handled, and the routes nobody
    called. All three are worth reporting: an unmatched call is coupling this
    cannot see, and an unhandled route is either dead or called from outside
    the repository — different problems, both invisible if only the matches
    are counted.
    """
    declarations = declared_routes(sources)
    calls = called_routes(sources)

    edges: list[ContractEdge] = []
    matched_calls: set[int] = set()
    matched_routes: set[int] = set()

    for call_index, call in enumerate(calls):
        for route_index, declaration in enumerate(declarations):
            if not routes_match(declaration.path, call.path):
                continue
            # An empty method on the declaration means the file serves several
            # and did not say which; treat that as matching anything.
            if declaration.method and declaration.method != call.method:
                continue
            if declaration.file == call.file:
                continue
            edges.append(
                ContractEdge(call.file, declaration.file, declaration.path, call.method)
            )
            matched_calls.add(call_index)
            matched_routes.add(route_index)

    unmatched = [c for i, c in enumerate(calls) if i not in matched_calls]
    uncalled = [d for i, d in enumerate(declarations) if i not in matched_routes]
    return sorted(set(edges), key=lambda e: (e.source, e.target, e.route)), unmatched, uncalled
