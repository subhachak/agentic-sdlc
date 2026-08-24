"""Import extraction and module assignment.

Shared by every adapter, because which imports a file declares is a property
of the file, not of where it was fetched from. Deliberately regex-based and
language-scoped rather than a full parse: the goal is a dependency signal
good enough to widen regression scope, and an approximate graph that is
rebuilt nightly beats an exact one that never ships.

Nothing here executes repository content.
"""

from __future__ import annotations

import hashlib
import json
import posixpath
import re
from dataclasses import dataclass, field

# Bumped whenever extraction or resolution changes, so a graph can say which
# indexer produced it. A blast radius derived by one version is not
# comparable with one derived by another.
INDEXER_VERSION = "2.0.0"

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

# What a file offers the rest of the codebase. A file's importers care about
# its exported surface, not its line count, so this is the projection that
# makes a later symbol-level diff possible without re-reading the repository.
_JS_EXPORT = re.compile(
    r"""(?m)^\s*export\s+(?:async\s+)?(?:default\s+)?"""
    r"""(?:function|class|const|let|var|interface|type|enum)\s+([A-Za-z_$][\w$]*)"""
)
_JS_EXPORT_LIST = re.compile(r"""(?m)^\s*export\s*\{([^}]*)\}""")
_PY_DEF = re.compile(r"""(?m)^(?:async\s+)?(?:def|class)\s+([A-Za-z_]\w*)""")

# A JS specifier that is shaped like an internal alias rather than an npm
# package. Distinguishing these is what stops a dropped tsconfig from being
# silently reported as "external dependency, nothing to see here".
_ALIAS_SHAPED = ("@/", "~/", "#/", "src/", "app/", "lib/")


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


def language_of(path: str) -> str:
    if path.endswith(PY_EXTENSIONS):
        return "python"
    if path.endswith((".ts", ".tsx")):
        return "typescript"
    if path.endswith(JS_EXTENSIONS):
        return "javascript"
    return "unknown"


def exported_symbols(path: str, text: str) -> list[str]:
    """The names a file makes available to its importers.

    Regex-derived and therefore incomplete — `export *` and computed names
    are invisible to it. It is stored on the node so a later change-semantics
    pass can ask whether an edit altered a file's public surface or only its
    internals, which is the difference between a wide radius and a narrow one.
    """
    if path.endswith(JS_EXTENSIONS):
        names = set(_JS_EXPORT.findall(text))
        for group in _JS_EXPORT_LIST.findall(text):
            for item in group.split(","):
                name = item.strip().split(" as ")[-1].strip()
                if name and name.isidentifier():
                    names.add(name)
        return sorted(names)

    if path.endswith(PY_EXTENSIONS):
        return sorted({n for n in _PY_DEF.findall(text) if not n.startswith("_")})

    return []


def file_metadata(path: str, text: str) -> dict:
    """Everything about a file that is true regardless of who imports it."""
    return {
        "language": language_of(path),
        "sha256": hashlib.sha256(text.encode("utf-8", "replace")).hexdigest(),
        "loc": text.count("\n") + (1 if text and not text.endswith("\n") else 0),
        "exports": exported_symbols(path, text),
    }


@dataclass
class ResolutionStats:
    """Where every import statement ended up.

    The previous counter incremented only for unresolved *relative* imports,
    so an aliased import that failed to resolve was indistinguishable from an
    npm package and the seed reported near-perfect resolution while dropping
    edges. These four buckets sum to `total`, which makes the omission
    visible instead of flattering.
    """

    total: int = 0
    resolved: int = 0
    external: int = 0
    unresolved_relative: int = 0
    unresolved_internal: int = 0
    missed_specs: dict[str, int] = field(default_factory=dict)

    @property
    def internal_total(self) -> int:
        return self.resolved + self.unresolved_relative + self.unresolved_internal

    @property
    def capture_rate(self) -> float:
        """Share of imports that look internal and were actually resolved."""
        return round(self.resolved / self.internal_total, 4) if self.internal_total else 1.0

    def record_miss(self, spec: str) -> None:
        self.missed_specs[spec] = self.missed_specs.get(spec, 0) + 1

    def as_dict(self) -> dict:
        return {
            "total_imports": self.total,
            "resolved": self.resolved,
            "external_package": self.external,
            "unresolved_relative": self.unresolved_relative,
            "unresolved_internal": self.unresolved_internal,
            "internal_capture_rate": self.capture_rate,
            "most_missed": sorted(
                self.missed_specs.items(), key=lambda kv: -kv[1]
            )[:10],
        }


def looks_internal(spec: str, from_path: str, aliases: dict[str, str], known: set[str]) -> bool:
    """Would we expect this specifier to resolve inside the repository?

    Only asked once a resolution attempt has already failed. A `true` here
    means an edge was dropped; a `false` means the import genuinely leaves
    the repository.
    """
    if spec.startswith("."):
        return True

    if from_path.endswith(JS_EXTENSIONS):
        if any(spec.startswith(a) for a in aliases):
            return True
        return spec.startswith(_ALIAS_SHAPED)

    # Python: an absolute import whose root package appears as a directory
    # segment somewhere in the tree is ours, however the source root is laid
    # out. `app.core.db` in a repo holding `services/api/app/core/db.py` is
    # not the PyPI package `app`.
    root = spec.split(".")[0]
    if not root:
        return False
    return any(root == segment for path in known for segment in path.split("/")[:-1])


def module_of(path: str, max_depth: int = 4) -> str:
    """A module is the directory a file lives in, collapsed to max_depth.

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
    # any file inside it — the caller only needs the module it maps to.
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
) -> tuple[dict[str, str], list[tuple[str, str]], list[tuple[str, str]], ResolutionStats]:
    """Return (path -> module), cross-module pairs, file-level imports, stats.

    The file-level pairs used to be computed and thrown away — only the module
    aggregate survived. That aggregate gives every file in a directory the same
    blast radius, so it cannot distinguish a leaf from a hub, which is the
    distinction impact analysis exists to make.
    """
    known = set(sources)
    aliases = aliases or {}
    modules = {path: module_of(path, max_depth) for path in sources}

    pairs: list[tuple[str, str]] = []
    imports: list[tuple[str, str]] = []
    stats = ResolutionStats()
    for path, text in sources.items():
        for ref in parse_imports(path, text):
            stats.total += 1
            if path.endswith(JS_EXTENSIONS):
                target = resolve_js(ref.spec, path, known, aliases, alias_root)
            else:
                target = resolve_py(ref.spec, path, known)

            if target is None:
                # Say which kind of failure this was. Counting only relative
                # misses is how 19 dropped edges hid behind "3 unresolved".
                if not looks_internal(ref.spec, path, aliases, known):
                    stats.external += 1
                elif ref.relative:
                    stats.unresolved_relative += 1
                    stats.record_miss(ref.spec)
                else:
                    stats.unresolved_internal += 1
                    stats.record_miss(ref.spec)
                continue

            stats.resolved += 1
            imports.append((path, target))
            src, dst = modules[path], modules.get(target)
            if dst and src != dst:
                pairs.append((src, dst))

    return modules, pairs, imports, stats
