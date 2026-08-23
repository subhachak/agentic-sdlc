"""Import extraction and component assignment.

Shared by every adapter, because which imports a file declares is a property
of the file, not of where it was fetched from. Deliberately regex-based and
language-scoped rather than a full parse: the goal is a dependency signal
good enough to widen regression scope, and an approximate graph that is
rebuilt nightly beats an exact one that never ships.

Nothing here executes repository content.
"""

from __future__ import annotations

import json
import posixpath
import re
from dataclasses import dataclass

JS_EXTENSIONS = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")
PY_EXTENSIONS = (".py",)
SOURCE_EXTENSIONS = JS_EXTENSIONS + PY_EXTENSIONS

# Directories that are never the client's own source.
IGNORED_SEGMENTS = {
    "node_modules", ".git", ".next", "dist", "build", "__pycache__",
    ".venv", "venv", "site-packages", ".mypy_cache", ".pytest_cache",
    "vendor", "third_party", "coverage",
}

_JS_FROM = re.compile(r"""(?:^|\n)\s*(?:import|export)\b[^;\n]*?\bfrom\s*['"]([^'"]+)['"]""")
_JS_BARE = re.compile(r"""(?:^|\n)\s*import\s*['"]([^'"]+)['"]""")
_JS_CALL = re.compile(r"""\b(?:require|import)\s*\(\s*['"]([^'"]+)['"]\s*\)""")

_PY_FROM = re.compile(r"""(?m)^\s*from\s+([.\w]+)\s+import\b""")
_PY_IMPORT = re.compile(r"""(?m)^\s*import\s+([.\w]+)""")


@dataclass(frozen=True)
class ImportRef:
    spec: str
    relative: bool


def is_ignored(path: str) -> bool:
    return any(segment in IGNORED_SEGMENTS for segment in path.split("/"))


def is_source(path: str) -> bool:
    return path.endswith(SOURCE_EXTENSIONS) and not is_ignored(path)


def parse_imports(path: str, text: str) -> list[ImportRef]:
    if path.endswith(JS_EXTENSIONS):
        specs = set()
        for pattern in (_JS_FROM, _JS_BARE, _JS_CALL):
            specs.update(pattern.findall(text))
        return [ImportRef(s, s.startswith(".")) for s in sorted(specs)]

    if path.endswith(PY_EXTENSIONS):
        specs = set(_PY_FROM.findall(text)) | set(_PY_IMPORT.findall(text))
        return [ImportRef(s, s.startswith(".")) for s in sorted(specs)]

    return []


def component_of(path: str, max_depth: int = 4) -> str:
    """A component is the directory a file lives in, collapsed to max_depth.

    A heuristic, and named as one. It matches how people talk about a
    codebase — "the nodes package", "the claims API" — without needing build
    metadata that differs per language and per client.
    """
    directory = posixpath.dirname(path)
    if not directory:
        return "root"
    return "/".join(directory.split("/")[:max_depth])


def load_aliases(tsconfig_text: str | None) -> dict[str, str]:
    """Path aliases from a tsconfig, so `@/lib/x` resolves like a real import.

    Without this, every aliased import in a Next.js codebase looks external
    and the dependency graph comes back nearly empty.
    """
    if not tsconfig_text:
        return {}
    try:
        # tsconfig allows comments and trailing commas; strip the common cases.
        cleaned = re.sub(r"//[^\n]*", "", tsconfig_text)
        cleaned = re.sub(r"/\*.*?\*/", "", cleaned, flags=re.S)
        cleaned = re.sub(r",(\s*[}\]])", r"\1", cleaned)
        config = json.loads(cleaned)
    except (json.JSONDecodeError, TypeError):
        return {}

    paths = (config.get("compilerOptions") or {}).get("paths") or {}
    aliases: dict[str, str] = {}
    for pattern, targets in paths.items():
        if not targets:
            continue
        aliases[pattern.rstrip("*")] = targets[0].rstrip("*").lstrip("./")
    return aliases


def resolve_js(spec: str, from_path: str, known: set[str], aliases: dict[str, str], root: str) -> str | None:
    if spec.startswith("."):
        base = posixpath.normpath(posixpath.join(posixpath.dirname(from_path), spec))
    else:
        matched = next((a for a in sorted(aliases, key=len, reverse=True) if spec.startswith(a)), None)
        if matched is None:
            return None  # an external package
        base = posixpath.normpath(posixpath.join(root, aliases[matched] + spec[len(matched):]))

    candidates = [base] + [base + ext for ext in JS_EXTENSIONS] + [
        f"{base}/index{ext}" for ext in JS_EXTENSIONS
    ] + [base + ".json"]
    return next((c for c in candidates if c in known), None)


def resolve_py(spec: str, from_path: str, known: set[str]) -> str | None:
    if spec.startswith("."):
        depth = len(spec) - len(spec.lstrip("."))
        parts = posixpath.dirname(from_path).split("/")
        base_dir = "/".join(parts[: len(parts) - (depth - 1)]) if depth > 1 else "/".join(parts)
        tail = spec.lstrip(".").replace(".", "/")
        base = posixpath.normpath(posixpath.join(base_dir, tail)) if tail else base_dir
    else:
        base = spec.replace(".", "/")

    for candidate in (f"{base}.py", f"{base}/__init__.py"):
        if candidate in known:
            return candidate

    # A package-relative import inside a source root, e.g. `app.core.db`
    # where files are stored as `control-plane/api/app/core/db.py`.
    for suffix in (f"/{base}.py", f"/{base}/__init__.py"):
        match = next((k for k in sorted(known) if k.endswith(suffix)), None)
        if match:
            return match

    # A namespace package: a directory with no __init__.py, which has been
    # legal since Python 3.3 and is common in src-layout projects. Resolve to
    # any file inside it — the caller only needs the component it maps to.
    for prefix in (f"{base}/", ):
        match = next((k for k in sorted(known) if k.startswith(prefix)), None)
        if match:
            return match
    match = next(
        (k for k in sorted(known) if f"/{base}/" in k),
        None,
    )
    return match


def build_index(
    sources: dict[str, str],
    *,
    aliases: dict[str, str] | None = None,
    alias_root: str = "",
    max_depth: int = 4,
) -> tuple[dict[str, str], list[tuple[str, str]], int]:
    """Return (path -> component), cross-component import pairs, unresolved count."""
    known = set(sources)
    aliases = aliases or {}
    components = {path: component_of(path, max_depth) for path in sources}

    pairs: list[tuple[str, str]] = []
    unresolved = 0
    for path, text in sources.items():
        for ref in parse_imports(path, text):
            if path.endswith(JS_EXTENSIONS):
                target = resolve_js(ref.spec, path, known, aliases, alias_root)
            else:
                target = resolve_py(ref.spec, path, known)

            if target is None:
                if ref.relative:
                    unresolved += 1  # a local import we failed to resolve
                continue
            src, dst = components[path], components.get(target)
            if dst and src != dst:
                pairs.append((src, dst))

    return components, pairs, unresolved
