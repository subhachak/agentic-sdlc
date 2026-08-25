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
from collections import Counter
from dataclasses import dataclass, field

from app.core.source_kinds import is_test_path

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
# `import type { X } from './y'` is erased at compile time. It is a real
# coupling for a type checker and no coupling at all at runtime, so counting
# it as a runtime edge overstates the blast radius of a change. Measured on
# this repository's sibling: 43 such statements were being counted as runtime.
_JS_TYPE_FROM = re.compile(
    r"""(?:^|\n)\s*(?:import|export)\s+type\b[^;\n]*?\bfrom\s*['"]([^'"]+)['"]"""
)
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


RUNTIME = "runtime"
TYPE_ONLY = "type-only"


@dataclass(frozen=True)
class ImportRef:
    spec: str
    relative: bool
    kind: str = RUNTIME


def is_ignored(path: str) -> bool:
    return any(segment in IGNORED_SEGMENTS for segment in path.split("/"))


def is_source(path: str) -> bool:
    return path.endswith(SOURCE_EXTENSIONS) and not is_ignored(path)


def parse_imports(path: str, text: str) -> list[ImportRef]:
    if path.endswith(JS_EXTENSIONS):
        # Counted rather than set-differenced: a specifier imported both ways
        # is a runtime edge, and the erasable import does not make the other
        # one disappear. Comparing occurrence counts is what distinguishes
        # "every import of this was a type import" from "one of them was".
        from_counts = Counter(_JS_FROM.findall(text))
        type_counts = Counter(_JS_TYPE_FROM.findall(text))
        side_effect = set(_JS_BARE.findall(text)) | set(_JS_CALL.findall(text))

        refs = []
        for spec in sorted(set(from_counts) | side_effect):
            erasable = (
                spec not in side_effect
                and type_counts[spec] > 0
                and type_counts[spec] >= from_counts[spec]
            )
            refs.append(
                ImportRef(spec, spec.startswith("."), TYPE_ONLY if erasable else RUNTIME)
            )
        return refs

    if path.endswith(PY_EXTENSIONS):
        # Python has no erasable import. `if TYPE_CHECKING:` blocks are the
        # equivalent, and resolving those needs the block structure rather
        # than a line pattern, so they are left as runtime for now.
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
    # Of the resolved edges, how many are erasable or originate in tests.
    # Reported so the headline edge count cannot be read as runtime coupling.
    type_only: int = 0
    from_tests: int = 0
    runtime_product: int = 0
    contract_edges: int = 0
    unmatched_calls: int = 0
    uncalled_routes: int = 0
    missed_specs: dict[str, int] = field(default_factory=dict)

    @property
    def internal_total(self) -> int:
        return self.resolved + self.unresolved_relative + self.unresolved_internal

    @property
    def capture_rate(self) -> float:
        """Share of imports that look internal and were actually resolved."""
        return round(self.resolved / self.internal_total, 4) if self.internal_total else 1.0

    def count_kind(self, kind: str, from_test: bool) -> None:
        if kind == TYPE_ONLY:
            self.type_only += 1
        if from_test:
            self.from_tests += 1
        if kind == RUNTIME and not from_test:
            self.runtime_product += 1

    def record_miss(self, spec: str) -> None:
        self.missed_specs[spec] = self.missed_specs.get(spec, 0) + 1

    def as_dict(self) -> dict:
        return {
            "total_imports": self.total,
            "resolved": self.resolved,
            "external_package": self.external,
            "unresolved_relative": self.unresolved_relative,
            "unresolved_internal": self.unresolved_internal,
            "type_only": self.type_only,
            "from_tests": self.from_tests,
            "runtime_product": self.runtime_product,
            "contract_edges": self.contract_edges,
            "unmatched_calls": self.unmatched_calls,
            "uncalled_routes": self.uncalled_routes,
            "internal_capture_rate": self.capture_rate,
            "most_missed": sorted(
                self.missed_specs.items(), key=lambda kv: -kv[1]
            )[:10],
        }


def looks_internal(
    spec: str, from_path: str, alias_sets: list[AliasSet], known: set[str]
) -> bool:
    """Would we expect this specifier to resolve inside the repository?

    Only asked once a resolution attempt has already failed. A `true` here
    means an edge was dropped; a `false` means the import genuinely leaves
    the repository.
    """
    if spec.startswith("."):
        return True

    if from_path.endswith(JS_EXTENSIONS):
        owner = alias_set_for(from_path, alias_sets)
        if owner and any(spec.startswith(a) for a in owner.aliases):
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


@dataclass(frozen=True)
class AliasSet:
    """Path aliases from one tsconfig, and the directory they resolve against.

    One per config file, not one per repository. A monorepo has a tsconfig per
    package, each mapping `@/*` to its own source root; applying the first one
    found to every package silently drops every aliased import in the others.
    Measured on this repository, that was 19 edges — reported as "3
    unresolved" because an unresolved alias was indistinguishable from an npm
    package.
    """

    directory: str            # where the tsconfig lives, "" for the repo root
    root: str                 # directory + baseUrl, what targets resolve against
    aliases: dict[str, str]

    def owns(self, path: str) -> bool:
        return not self.directory or path.startswith(f"{self.directory}/")


def load_aliases(tsconfig_text: str | None) -> dict[str, str]:
    """Path aliases from a tsconfig, so `@/lib/x` resolves like a real import.

    Without this, every aliased import in a Next.js codebase looks external
    and the dependency graph comes back nearly empty.
    """
    config = _parse_tsconfig(tsconfig_text)
    paths = (config.get("compilerOptions") or {}).get("paths") or {}
    aliases: dict[str, str] = {}
    for pattern, targets in paths.items():
        if not targets:
            continue
        aliases[pattern.rstrip("*")] = targets[0].rstrip("*").lstrip("./")
    return aliases


def _strip_jsonc_comments(text: str) -> str:
    """Remove `//` and `/* */` comments without touching string contents.

    A regex cannot do this. `"@/*": ["./src/*"]` contains `/*`, and the next
    `*/` is inside a later `"**/*.ts"` — so a non-greedy block-comment strip
    deletes the whole `paths` block and everything up to the include list. The
    tsconfig then fails to parse, `load_aliases` returns nothing, and every
    aliased import in that package is filed as an external npm package.

    That is the real cause of the 19 dropped `@/...` edges measured on this
    repository — not, as first diagnosed, the single-tsconfig lookup. Both
    were wrong; only this one was firing here.
    """
    out: list[str] = []
    index = 0
    length = len(text)
    in_string = False
    escaped = False

    while index < length:
        char = text[index]

        if in_string:
            out.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            index += 1
            continue

        if char == '"':
            in_string = True
            out.append(char)
            index += 1
            continue

        if char == "/" and index + 1 < length:
            following = text[index + 1]
            if following == "/":
                while index < length and text[index] != "\n":
                    index += 1
                continue
            if following == "*":
                index += 2
                while index + 1 < length and not (
                    text[index] == "*" and text[index + 1] == "/"
                ):
                    index += 1
                index += 2
                continue

        out.append(char)
        index += 1

    return "".join(out)


def _parse_tsconfig(tsconfig_text: str | None) -> dict:
    if not tsconfig_text:
        return {}
    try:
        cleaned = _strip_jsonc_comments(tsconfig_text)
        # Trailing commas. Still a regex, and still able to corrupt a string
        # literal containing ",}" — which no tsconfig has, unlike `/*`.
        cleaned = re.sub(r",(\s*[}\]])", r"\1", cleaned)
        config = json.loads(cleaned)
    except (json.JSONDecodeError, TypeError):
        return {}
    return config if isinstance(config, dict) else {}


def load_alias_sets(tsconfigs: dict[str, str]) -> list[AliasSet]:
    """Build one alias set per tsconfig, keyed by where the config lives.

    `paths` resolve against `baseUrl` when it is set and against the config's
    own directory otherwise, which is what makes a package-local `"@/*":
    ["./*"]` mean that package's root rather than the repository's.
    """
    sets: list[AliasSet] = []
    for config_path, text in tsconfigs.items():
        aliases = load_aliases(text)
        if not aliases:
            continue
        directory = posixpath.dirname(config_path)
        base_url = (
            (_parse_tsconfig(text).get("compilerOptions") or {}).get("baseUrl") or "."
        )
        root = posixpath.normpath(posixpath.join(directory, base_url))
        sets.append(
            AliasSet(directory=directory, root="" if root == "." else root, aliases=aliases)
        )
    # Deepest first, so the nearest config to a file wins.
    return sorted(sets, key=lambda a: -len(a.directory))


def alias_set_for(path: str, alias_sets: list[AliasSet]) -> AliasSet | None:
    """The tsconfig that governs this file: the nearest one above it."""
    return next((a for a in alias_sets if a.owns(path)), None)


def resolve_js(
    spec: str, from_path: str, known: set[str], alias_sets: list[AliasSet]
) -> str | None:
    if spec.startswith("."):
        base = posixpath.normpath(posixpath.join(posixpath.dirname(from_path), spec))
    else:
        owner = alias_set_for(from_path, alias_sets)
        if owner is None:
            return None  # an external package
        matched = next(
            (a for a in sorted(owner.aliases, key=len, reverse=True) if spec.startswith(a)),
            None,
        )
        if matched is None:
            return None
        target = owner.aliases[matched] + spec[len(matched):]
        base = posixpath.normpath(posixpath.join(owner.root, target))

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


@dataclass(frozen=True, order=True)
class ResolvedImport:
    source: str
    target: str
    kind: str            # runtime | type-only
    from_test: bool


def build_index(
    sources: dict[str, str],
    *,
    alias_sets: list[AliasSet] | None = None,
    max_depth: int = 4,
) -> tuple[dict[str, str], list[tuple[str, str]], list[ResolvedImport], ResolutionStats]:
    """Return (path -> module), cross-module pairs, file-level imports, stats.

    The file-level imports used to be computed and thrown away — only the
    module aggregate survived. That aggregate gives every file in a directory
    the same blast radius, so it cannot distinguish a leaf from a hub, which
    is the distinction impact analysis exists to make.

    Every edge is classified rather than filtered. A type-only import is real
    coupling for a type checker and none at runtime; a test's import is how
    you find which tests to run, but not evidence that a module is widely
    depended on. Which of those a consumer wants differs by consumer, so the
    graph keeps them all and says which is which.

    Module rollup counts runtime, non-test edges only. It is what the design
    agent is shown as "what depends on what", and that answer should describe
    the product, not its test suite.
    """
    known = set(sources)
    alias_sets = alias_sets or []
    modules = {path: module_of(path, max_depth) for path in sources}

    pairs: list[tuple[str, str]] = []
    imports: list[ResolvedImport] = []
    stats = ResolutionStats()
    for path, text in sources.items():
        from_test = is_test_path(path)
        for ref in parse_imports(path, text):
            stats.total += 1
            if path.endswith(JS_EXTENSIONS):
                target = resolve_js(ref.spec, path, known, alias_sets)
            else:
                target = resolve_py(ref.spec, path, known)

            if target is None:
                # Say which kind of failure this was. Counting only relative
                # misses is how 19 dropped edges hid behind "3 unresolved".
                if not looks_internal(ref.spec, path, alias_sets, known):
                    stats.external += 1
                elif ref.relative:
                    stats.unresolved_relative += 1
                    stats.record_miss(ref.spec)
                else:
                    stats.unresolved_internal += 1
                    stats.record_miss(ref.spec)
                continue

            stats.resolved += 1
            stats.count_kind(ref.kind, from_test)
            imports.append(ResolvedImport(path, target, ref.kind, from_test))

            src, dst = modules[path], modules.get(target)
            if dst and src != dst and ref.kind == RUNTIME and not from_test:
                pairs.append((src, dst))

    return modules, pairs, imports, stats
