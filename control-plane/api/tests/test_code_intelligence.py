"""Deriving a module graph from source.

The parser is regex-based and approximate on purpose — a dependency signal
good enough to widen regression scope, rebuilt on demand. These tests pin
what it must get right for that to be true.
"""

from __future__ import annotations

import pytest

from app.adapters.code_intelligence.local_path import LocalPathCodeIntelligence
from app.adapters.code_intelligence.parsing import (
    INDEXER_VERSION,
    build_index,
    file_metadata,
    module_of,
    is_ignored,
    is_source,
    load_aliases,
    load_alias_sets,
    parse_imports,
    resolve_js,
    resolve_py,
)
from app.core.context_graph import Assertion, NodeSpec
from app.core.seeding import assertions_from_index, seed
from app.ports.code_intelligence import (
    CodeDependency,
    CodeFile,
    CodeIndex,
    CodeModule,
    IndexProvenance,
)
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
    assert module_of("control-plane/api/app/core/db.py", 4) == "control-plane/api/app/core"
    assert module_of("control-plane/api/app/core/db.py", 2) == "control-plane/api"
    assert module_of("main.py") == "root"


def test_tsconfig_aliases_are_read():
    assert load_aliases('{"compilerOptions":{"paths":{"@/*":["./*"]}}}') == {"@/": ""}


def test_a_tsconfig_with_comments_still_parses():
    """Next.js ships tsconfig files with comments and trailing commas, and a
    parser that chokes on them reports every aliased import as external."""
    assert load_aliases('{\n // a comment\n "compilerOptions":{"paths":{"@/*":["./src/*"]},},\n}') == {"@/": "src/"}


# --- resolution ------------------------------------------------------------


ROOT_ALIASES = load_alias_sets({"tsconfig.json": '{"compilerOptions":{"paths":{"@/*":["./*"]}}}'})


def test_a_relative_js_import_resolves_through_extensions():
    known = {"src/lib/util.ts", "src/app/page.tsx"}
    assert resolve_js("../lib/util", "src/app/page.tsx", known, []) == "src/lib/util.ts"


def test_an_aliased_js_import_resolves():
    known = {"lib/data.json", "app/page.tsx"}
    assert resolve_js("@/lib/data.json", "app/page.tsx", known, ROOT_ALIASES) == "lib/data.json"


def test_an_external_package_resolves_to_nothing():
    assert resolve_js("react", "app/page.tsx", {"app/page.tsx"}, ROOT_ALIASES) is None


def test_a_tsconfig_whose_paths_contain_a_star_still_parses():
    """The bug that actually dropped this repository's 19 aliased edges. A
    regex block-comment strip sees `/*` inside `"@/*"` and deletes everything
    up to the next `*/`, which is inside `"**/*.ts"` further down — taking the
    whole `paths` block with it. The config then fails to parse and every
    aliased import in that package is filed as an npm package."""
    text = """{
      "compilerOptions": {
        "paths": { "@/*": ["./src/*"] }
      },
      "include": ["next-env.d.ts", "**/*.ts", "**/*.tsx"]
    }"""

    assert load_aliases(text) == {"@/": "src/"}


def test_real_comments_are_still_stripped():
    text = """{
      // the source root
      "compilerOptions": {
        /* block comment */
        "paths": { "@/*": ["./app/*"] }
      }
    }"""

    assert load_aliases(text) == {"@/": "app/"}


def test_a_comment_marker_inside_a_string_is_not_a_comment():
    text = '{"compilerOptions":{"paths":{"@/*":["./a//b/*"]}}}'
    assert load_aliases(text) == {"@/": "a//b/"}


def test_each_package_resolves_against_its_own_tsconfig():
    """The bug this exists to catch: one tsconfig applied to a whole monorepo.
    Both packages map `@/*` to their own root, so a single alias table sends
    every import in one of them to a file that does not exist. Measured on
    this repository, that dropped 19 edges — and reported 3."""
    tsconfigs = {
        "web/tsconfig.json": '{"compilerOptions":{"baseUrl":".","paths":{"@/*":["./src/*"]}}}',
        "docs/tsconfig.json": '{"compilerOptions":{"baseUrl":".","paths":{"@/*":["./lib/*"]}}}',
    }
    alias_sets = load_alias_sets(tsconfigs)
    known = {"web/src/api.ts", "docs/lib/api.ts", "web/page.tsx", "docs/page.tsx"}

    assert resolve_js("@/api", "web/page.tsx", known, alias_sets) == "web/src/api.ts"
    assert resolve_js("@/api", "docs/page.tsx", known, alias_sets) == "docs/lib/api.ts"


def test_the_nearest_tsconfig_wins_over_one_further_up():
    tsconfigs = {
        "tsconfig.json": '{"compilerOptions":{"paths":{"@/*":["./shared/*"]}}}',
        "web/tsconfig.json": '{"compilerOptions":{"paths":{"@/*":["./src/*"]}}}',
    }
    alias_sets = load_alias_sets(tsconfigs)
    known = {"shared/api.ts", "web/src/api.ts", "web/page.tsx", "page.tsx"}

    assert resolve_js("@/api", "web/page.tsx", known, alias_sets) == "web/src/api.ts"
    assert resolve_js("@/api", "page.tsx", known, alias_sets) == "shared/api.ts"


# --- edge classification ---------------------------------------------------


def test_a_type_only_import_is_marked_as_erasable():
    """`import type` is real coupling for a type checker and none at runtime.
    Counting it as a runtime edge overstates what a change can break."""
    sources = {
        "web/a.ts": "import type { Claim } from './model'\nimport { fetchClaims } from './api'",
        "web/model.ts": "export type Claim = { id: string }",
        "web/api.ts": "export function fetchClaims() {}",
    }
    _, _, imports, stats = build_index(sources, max_depth=1)
    by_target = {i.target: i for i in imports}

    assert by_target["web/model.ts"].kind == "type-only"
    assert by_target["web/api.ts"].kind == "runtime"
    assert stats.type_only == 1
    assert stats.runtime_product == 1


def test_an_import_used_both_ways_counts_as_runtime():
    sources = {
        "web/a.ts": "import type { Claim } from './model'\nimport { load } from './model'",
        "web/model.ts": "export function load() {}",
    }
    _, _, imports, _ = build_index(sources, max_depth=1)
    assert [i.kind for i in imports] == ["runtime"]


def test_a_test_file_import_is_marked_and_kept_out_of_the_module_rollup():
    """30% of this repository's import edges originate in tests. They are real
    edges — they are how you find which tests to run — but a module's
    dependents should describe the product, not its test suite."""
    sources = {
        "app/core/db.py": "",
        "app/api/route.py": "from app.core.db import x",
        "tests/test_db.py": "from app.core.db import x",
    }
    _, pairs, imports, stats = build_index(sources, max_depth=2)
    by_source = {i.source: i for i in imports}

    assert by_source["tests/test_db.py"].from_test is True
    assert by_source["app/api/route.py"].from_test is False
    assert stats.from_tests == 1
    # The test edge survives at file level and is absent from the rollup.
    assert pairs == [("app/api", "app/core")]


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
        "app/core/a.py": "from app.core import b",     # same module
        "app/core/b.py": "",
        "app/api/c.py": "from app.core import a",      # crosses
    }
    _, pairs, _imports, _ = build_index(sources, max_depth=2)

    assert pairs == [("app/api", "app/core")]


def test_unresolvable_local_imports_are_counted_not_silently_dropped():
    sources = {"app/a.py": "from .missing import thing"}
    _, _, _imports, stats = build_index(sources, max_depth=2)
    assert stats.unresolved_relative == 1
    assert stats.capture_rate == 0.0


def test_external_packages_do_not_count_as_unresolved():
    sources = {"app/a.py": "import os\nimport httpx"}
    _, pairs, _imports, stats = build_index(sources, max_depth=2)
    assert (pairs, stats.unresolved_relative, stats.unresolved_internal) == ([], 0, 0)
    assert stats.external == 2


def test_an_unresolved_alias_is_reported_not_filed_as_an_npm_package():
    """The failure this exists to catch: a monorepo whose tsconfig was not
    found makes every `@/...` import look like an external dependency. The
    old counter only incremented for relative imports, so the seed reported
    perfect resolution while dropping every aliased edge."""
    sources = {"web/page.tsx": "import { api } from '@/lib/api'\nimport React from 'react'"}
    _, _, imports, stats = build_index(sources, max_depth=2)

    assert imports == []
    assert stats.unresolved_internal == 1   # the alias
    assert stats.external == 1              # react, genuinely external
    assert stats.capture_rate == 0.0
    assert stats.missed_specs == {"@/lib/api": 1}


def test_absolute_python_imports_that_should_have_resolved_are_reported():
    sources = {
        "svc/app/api.py": "from app.core.gone import thing\nimport json",
        "svc/app/core/__init__.py": "",
    }
    _, _, _imports, stats = build_index(sources, max_depth=2)

    assert stats.unresolved_internal == 1   # app.core.gone is ours and missing
    assert stats.external == 1              # json is not


def test_a_file_carries_its_language_hash_and_exported_surface():
    text = "export function alpha() {}\nexport const beta = 1\n"
    meta = file_metadata("web/thing.ts", text)

    assert meta["language"] == "typescript"
    assert meta["exports"] == ["alpha", "beta"]
    assert len(meta["sha256"]) == 64
    assert meta["loc"] == 2


def test_python_exports_omit_private_names():
    meta = file_metadata("app/x.py", "def public():\n    pass\ndef _private():\n    pass\n")
    assert meta["exports"] == ["public"]


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

    assert {c.id for c in index.modules} == {"app/core", "app/api"}
    assert [(d.source, d.target) for d in index.dependencies] == [("app/api", "app/core")]
    assert all("node_modules" not in f.path for f in index.files)


# --- seeding into the graph ------------------------------------------------


INDEX = CodeIndex(
    repo="acme/thing", ref="main",
    modules=[CodeModule(id="core", paths=["core/a.py", "core/b.py"]),
                CodeModule(id="api", paths=["api/c.py"])],
    files=[
        CodeFile(path="core/a.py", module="core", language="python",
                 sha256="0" * 64, loc=4, exports=["alpha"]),
        CodeFile(path="core/b.py", module="core", language="python",
                 sha256="1" * 64, loc=2, exports=[]),
        CodeFile(path="api/c.py", module="api", language="python",
                 sha256="2" * 64, loc=9, exports=["handler"]),
    ],
    dependencies=[CodeDependency(source="api", target="core", weight=3)],
    provenance=IndexProvenance(
        commit_sha="a" * 40,
        indexer_version=INDEXER_VERSION,
        indexed_at="2026-08-24T00:00:00+00:00",
        files_indexed=3,
        total_imports=5,
        resolved=3,
        external_package=2,
        internal_capture_rate=1.0,
    ),
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

    assert summary["modules"] == 2
    assert summary["edges_written"] == 4  # three files + one dependency
    counts = await graph.counts()
    assert counts["nodes"]["MODULE"] == 2
    assert counts["nodes"]["SOURCE_ARTIFACT"] == 3


@pytest.mark.asyncio
async def test_naming_a_component_again_does_not_erase_what_is_known():
    """Regression: the dependency assertions carry no file count, and used to
    overwrite the projection the BELONGS_TO assertions had just written — so
    every module that had a dependency reported zero files."""
    graph = InMemoryContextGraph()
    await seed(graph, _Indexer(INDEX), repo="acme/thing")

    api = next(n for n in graph.nodes.values()
               if n["type"] == "MODULE" and n["external_id"] == "api")
    assert api["projection"]["file_count"] == 1


@pytest.mark.asyncio
async def test_re_seeding_rebuilds_rather_than_accumulating():
    """Re-seeding writes the same structure again, having first removed what
    the previous index wrote. What must not change is the result: the same
    repository indexed twice is the same graph, not a doubled one."""
    graph = InMemoryContextGraph()
    first = await seed(graph, _Indexer(INDEX), repo="acme/thing")
    before = await graph.counts()

    second = await seed(graph, _Indexer(INDEX), repo="acme/thing")

    assert first["edges_written"] == second["edges_written"] == 4
    assert second["removed"] == {"edges": 4, "nodes": 5}
    assert await graph.counts() == before


@pytest.mark.asyncio
async def test_a_rebuild_drops_nodes_whose_type_was_renamed():
    """Node identity includes the node's type, so renaming a type strands the
    old nodes beside the new ones. Purging by phase is what stops a rename
    from leaving a parallel graph behind."""
    graph = InMemoryContextGraph()
    await graph.ingest(
        "seed",
        "code-index",
        [Assertion(
            "BELONGS_TO",
            NodeSpec("SOURCE_ARTIFACT", "code", "api/c.py", {}),
            NodeSpec("MODULE", "code", "api", {}),
        )],
    )
    stale = await graph.counts()
    assert stale["nodes"]["MODULE"] == 1

    await seed(graph, _Indexer(INDEX), repo="acme/thing")

    modules = {n["external_id"] for n in graph.nodes.values() if n["type"] == "MODULE"}
    assert modules == {"api", "core"}          # not a third, stranded one
    assert (await graph.counts())["nodes"]["SOURCE_ARTIFACT"] == 3


@pytest.mark.asyncio
async def test_a_rebuild_keeps_what_another_phase_asserted():
    """Purge is scoped to the phase that wrote it. A release that recorded
    which files it contained is an audit record, and re-indexing the
    repository must not erase it."""
    graph = InMemoryContextGraph()
    await seed(graph, _Indexer(INDEX), repo="acme/thing")
    await graph.ingest(
        "run-1",
        "release",
        [Assertion(
            "CONTAINS",
            NodeSpec("RELEASE", "cd", "r-1", {}),
            NodeSpec("SOURCE_ARTIFACT", "code", "api/c.py", {}),
        )],
    )

    await seed(graph, _Indexer(INDEX), repo="acme/thing")

    kept = [e for e in graph.edges if e["type"] == "CONTAINS"]
    assert len(kept) == 1
    assert any(
        n["type"] == "SOURCE_ARTIFACT" and n["external_id"] == "api/c.py"
        for n in graph.nodes.values()
    )


@pytest.mark.asyncio
async def test_the_seed_reports_the_commit_it_indexed():
    graph = InMemoryContextGraph()
    summary = await seed(graph, _Indexer(INDEX), repo="acme/thing")

    assert summary["commit_sha"] == "a" * 40
    assert summary["pinned"] is True
    assert summary["indexer_version"] == INDEXER_VERSION
    assert summary["resolution"]["internal_capture_rate"] == 1.0

    artifact = next(
        n for n in graph.nodes.values()
        if n["type"] == "SOURCE_ARTIFACT" and n["external_id"] == "api/c.py"
    )
    assert artifact["projection"]["language"] == "python"
    assert artifact["projection"]["exports"] == ["handler"]


class _Indexer:
    def __init__(self, index: CodeIndex) -> None:
        self._index = index

    async def index(self, repo: str, ref: str = "main") -> CodeIndex:
        return self._index


def test_file_level_imports_are_kept_not_only_the_module_aggregate():
    """They used to be computed and discarded. On one real repository that
    threw away 912 edges to keep 41 — and with them the ability to tell a leaf
    from a hub."""
    sources = {
        "app/core/db.py": "",
        "app/core/svc.py": "from app.core.db import x",
        "app/api/route.py": "from app.core.db import x",
    }
    _, pairs, imports, _ = build_index(sources, max_depth=2)

    assert sorted((i.source, i.target) for i in imports) == [
        ("app/api/route.py", "app/core/db.py"),
        ("app/core/svc.py", "app/core/db.py"),
    ]
    # the module aggregate keeps only the one crossing edge
    assert pairs == [("app/api", "app/core")]
