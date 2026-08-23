"""Deriving a component graph from source.

The parser is regex-based and approximate on purpose — a dependency signal
good enough to widen regression scope, rebuilt on demand. These tests pin
what it must get right for that to be true.
"""

from __future__ import annotations

import pytest

from app.adapters.code_intelligence.local_path import LocalPathCodeIntelligence
from app.adapters.code_intelligence.parsing import (
    build_index,
    component_of,
    is_ignored,
    is_source,
    load_aliases,
    parse_imports,
    resolve_js,
    resolve_py,
)
from app.core.context_graph import Assertion
from app.core.seeding import assertions_from_index, seed
from app.ports.code_intelligence import CodeComponent, CodeDependency, CodeIndex
from tests.graph_doubles import InMemoryContextGraph


# --- parsing ---------------------------------------------------------------


def test_js_import_forms_are_all_found():
    text = """
    import a from "./a";
    import { b } from '../b';
    export { c } from "@/c";
    const d = require("./d");
    const e = await import("./e");
    """
    specs = {ref.spec for ref in parse_imports("src/x.ts", text)}
    assert specs == {"./a", "../b", "@/c", "./d", "./e"}


def test_python_import_forms_are_found():
    specs = {r.spec for r in parse_imports("a/b.py", "from app.core import db\nimport os\nfrom . import x")}
    assert {"app.core", "os"} <= specs


def test_a_non_source_file_yields_nothing():
    assert parse_imports("README.md", "import x from 'y'") == []


def test_vendored_directories_are_ignored():
    assert is_ignored("node_modules/react/index.js")
    assert is_ignored("a/.venv/lib/x.py")
    assert not is_ignored("app/core/db.py")
    assert not is_source("node_modules/react/index.js")


def test_a_component_is_a_directory_collapsed_to_depth():
    assert component_of("control-plane/api/app/core/db.py", 4) == "control-plane/api/app/core"
    assert component_of("control-plane/api/app/core/db.py", 2) == "control-plane/api"
    assert component_of("main.py") == "root"


def test_tsconfig_aliases_are_read():
    assert load_aliases('{"compilerOptions":{"paths":{"@/*":["./*"]}}}') == {"@/": ""}


def test_a_tsconfig_with_comments_still_parses():
    """Next.js ships tsconfig files with comments and trailing commas, and a
    parser that chokes on them reports every aliased import as external."""
    assert load_aliases('{\n // a comment\n "compilerOptions":{"paths":{"@/*":["./src/*"]},},\n}') == {"@/": "src/"}


# --- resolution ------------------------------------------------------------


def test_a_relative_js_import_resolves_through_extensions():
    known = {"src/lib/util.ts", "src/app/page.tsx"}
    assert resolve_js("../lib/util", "src/app/page.tsx", known, {}, "") == "src/lib/util.ts"


def test_an_aliased_js_import_resolves():
    known = {"lib/data.json", "app/page.tsx"}
    assert resolve_js("@/lib/data.json", "app/page.tsx", known, {"@/": ""}, "") == "lib/data.json"


def test_an_external_package_resolves_to_nothing():
    assert resolve_js("react", "app/page.tsx", {"app/page.tsx"}, {}, "") is None


def test_a_python_import_resolves_inside_a_source_root():
    known = {"control-plane/api/app/core/db.py"}
    assert resolve_py("app.core.db", "control-plane/api/app/main.py", known) == (
        "control-plane/api/app/core/db.py"
    )


def test_a_python_package_import_resolves_to_its_init():
    known = {"pkg/__init__.py"}
    assert resolve_py("pkg", "main.py", known) == "pkg/__init__.py"


# --- index building --------------------------------------------------------


def test_only_cross_component_imports_become_dependencies():
    sources = {
        "app/core/a.py": "from app.core import b",     # same component
        "app/core/b.py": "",
        "app/api/c.py": "from app.core import a",      # crosses
    }
    _, pairs, _ = build_index(sources, max_depth=2)

    assert pairs == [("app/api", "app/core")]


def test_unresolvable_local_imports_are_counted_not_silently_dropped():
    sources = {"app/a.py": "from .missing import thing"}
    _, _, unresolved = build_index(sources, max_depth=2)
    assert unresolved == 1


def test_external_packages_do_not_count_as_unresolved():
    sources = {"app/a.py": "import os\nimport httpx"}
    _, pairs, unresolved = build_index(sources, max_depth=2)
    assert (pairs, unresolved) == ([], 0)


# --- the local adapter -----------------------------------------------------


@pytest.mark.asyncio
async def test_a_directory_indexes_end_to_end(tmp_path):
    (tmp_path / "app" / "core").mkdir(parents=True)
    (tmp_path / "app" / "api").mkdir(parents=True)
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "app" / "core" / "db.py").write_text("VALUE = 1\n")
    (tmp_path / "app" / "api" / "route.py").write_text("from app.core.db import VALUE\n")
    (tmp_path / "node_modules" / "junk.js").write_text("import x from './y'\n")

    index = await LocalPathCodeIntelligence(tmp_path, max_depth=2).index("", "local")

    assert {c.id for c in index.components} == {"app/core", "app/api"}
    assert [(d.source, d.target) for d in index.dependencies] == [("app/api", "app/core")]
    assert all("node_modules" not in f.path for f in index.files)


# --- seeding into the graph ------------------------------------------------


INDEX = CodeIndex(
    repo="acme/thing", ref="main",
    components=[CodeComponent(id="core", paths=["core/a.py", "core/b.py"]),
                CodeComponent(id="api", paths=["api/c.py"])],
    dependencies=[CodeDependency(source="api", target="core", weight=3)],
)


def test_seeding_asserts_structure_but_never_coverage():
    """Only a run that tested something may claim VERIFIED_BY or COVERS. The
    seeder knows the codebase, not what was tested."""
    edges = {a.edge for a in assertions_from_index(INDEX)}
    assert edges == {"BELONGS_TO", "DEPENDS_ON"}


def test_dependency_weight_survives_onto_the_edge():
    dep = next(a for a in assertions_from_index(INDEX) if a.edge == "DEPENDS_ON")
    assert dep.attributes["weight"] == 3


@pytest.mark.asyncio
async def test_seeding_writes_components_and_files():
    graph = InMemoryContextGraph()
    summary = await seed(graph, _Indexer(INDEX), repo="acme/thing")

    assert summary["components"] == 2
    assert summary["edges_written"] == 4  # three files + one dependency
    counts = await graph.counts()
    assert counts["nodes"]["COMPONENT"] == 2
    assert counts["nodes"]["SOURCE_ARTIFACT"] == 3


@pytest.mark.asyncio
async def test_naming_a_component_again_does_not_erase_what_is_known():
    """Regression: the dependency assertions carry no file count, and used to
    overwrite the projection the BELONGS_TO assertions had just written — so
    every component that had a dependency reported zero files."""
    graph = InMemoryContextGraph()
    await seed(graph, _Indexer(INDEX), repo="acme/thing")

    api = next(n for n in graph.nodes.values()
               if n["type"] == "COMPONENT" and n["external_id"] == "api")
    assert api["projection"]["file_count"] == 1


@pytest.mark.asyncio
async def test_re_seeding_is_idempotent():
    graph = InMemoryContextGraph()
    first = await seed(graph, _Indexer(INDEX), repo="acme/thing")
    second = await seed(graph, _Indexer(INDEX), repo="acme/thing")

    assert first["edges_written"] == 4
    assert second["edges_written"] == 0


class _Indexer:
    def __init__(self, index: CodeIndex) -> None:
        self._index = index

    async def index(self, repo: str, ref: str = "main") -> CodeIndex:
        return self._index
