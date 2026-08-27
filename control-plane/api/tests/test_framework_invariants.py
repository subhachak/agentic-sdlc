"""The rules that make this a framework rather than one client's build.

Two failure modes matter more than any feature. The first is arriving at a
client and finding that satisfying them means forking: an extension point
that is really a core-only dict, a port with no factory, a decision the core
makes about a concrete vendor. The second is the framework contradicting
itself in front of them: two modules that answer the same question
differently, a docstring promising a control that does not exist, a
cross-plane contract neither side validates.

Both are structural, so both are testable. Every rule here was written
because breaking it was possible, and most of them were broken when this
file was added.
"""

from __future__ import annotations

import ast
import importlib
import inspect
import re
import subprocess
import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "app"


def _module_source(path: Path) -> ast.Module:
    return ast.parse(path.read_text(), filename=str(path))


def _imports(path: Path) -> set[str]:
    out: set[str] = set()
    for node in ast.walk(_module_source(path)):
        if isinstance(node, ast.Import):
            out.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            out.add(node.module)
    return out


# ── pluggability ──────────────────────────────────────────────────────────


def _protocols_in(package: Path) -> dict[str, Path]:
    found: dict[str, Path] = {}
    for path in sorted(package.glob("*.py")):
        if path.name == "__init__.py":
            continue
        for node in _module_source(path).body:
            if isinstance(node, ast.ClassDef) and any(
                isinstance(b, ast.Name) and b.id == "Protocol" for b in node.bases
            ):
                found[node.name] = path
    return found


PORTS = _protocols_in(APP / "ports")


def test_there_are_ports_to_check():
    assert len(PORTS) >= 10


@pytest.mark.parametrize("protocol", sorted(PORTS))
def test_every_port_can_be_built_without_editing_core(protocol: str):
    """A port with no factory is a port a client cannot swap.

    The graph store was exactly this: a Protocol like every other, but
    constructed directly in main.py, so a client wanting Postgres or a hosted
    graph service had to edit the platform's entry point.
    """
    from app.adapters import registry

    # Optional capabilities are discovered by duck-typing, not required.
    # Read from the ports package rather than listed here, so adding one is
    # a deliberate act recorded beside the port it describes.
    from app.ports import OPTIONAL_CAPABILITIES

    if protocol in OPTIONAL_CAPABILITIES:
        pytest.skip(f"{protocol} is an optional capability")

    expected = "build_" + _snake(protocol)
    assert hasattr(registry, expected), (
        f"{protocol} has no {expected}() in the adapter registry, so selecting a "
        f"different implementation means editing core"
    )


def _snake(name: str) -> str:
    # Acronym-aware: LLMProvider is llm_provider, not l_l_m_provider.
    step = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", step).lower()


def test_the_context_graph_is_a_port_like_any_other():
    """It is the platform's central abstraction and it lived in core, which
    is why nothing noticed it had no factory. The storage engine is not the
    architecture — the versioned semantic model is."""
    assert "ContextGraphStore" in PORTS, (
        "ContextGraphStore is not in app/ports, so it reads as core machinery "
        "rather than as something a client replaces"
    )


# ── the core stays clean ──────────────────────────────────────────────────


CORE_MODULES = sorted((APP / "core").glob("*.py")) + sorted((APP / "graph").glob("*.py"))


@pytest.mark.parametrize("path", CORE_MODULES, ids=lambda p: p.name)
def test_core_never_imports_a_concrete_adapter(path: Path):
    """The core may depend on a port, never on an implementation.

    Someone needs a repository listing in a hurry and imports the GitHub
    adapter where it is convenient rather than where it belongs; the platform
    is then GitHub-shaped and the next client has to fork it.
    """
    offenders = sorted(
        name
        for name in _imports(path)
        if name.startswith("app.adapters.") and name != "app.adapters.registry"
    )
    assert offenders == [], f"{path.name} imports concrete adapters: {offenders}"


# ── extension without a fork ──────────────────────────────────────────────


def test_impact_semantics_can_be_extended_from_outside_core():
    """A client relationship type must be teachable, not editable.

    The registry was a module-level dict, so a client with a
    `x_depends_on_policy` edge that genuinely propagates had two options:
    have it ignored, or edit app/core/impact.py. Both are the fork this
    exists to prevent.
    """
    from app.core import impact

    assert hasattr(impact, "register"), (
        "no impact.register() — contributing a relationship's semantics means "
        "editing the core registry"
    )

    before = dict(impact.SEMANTICS)
    try:
        impact.register(
            impact.Semantics(edge="x_client_thing", truth="inferred", direction="to_source")
        )
        out = impact.assess(
            impact.ChangeSet(("b.ts",)),
            [impact.Edge(type="x_client_thing", source="a.ts", target="b.ts")],
            policy=impact.Policy(edges=frozenset({"x_client_thing"})),
        )
        assert out.affected == ["a.ts"]
    finally:
        impact.SEMANTICS.clear()
        impact.SEMANTICS.update(before)


def test_every_edge_type_has_a_declared_impact_stance():
    """Adding a relationship must force a decision about what it propagates.

    Otherwise a new edge type is silently untraversed, and the impact set is
    quietly wrong in a way nothing reports.
    """
    from app.core.impact import SEMANTICS, NON_PROPAGATING
    from app.graph.ontology import EdgeType

    undeclared = sorted(
        e.value for e in EdgeType if e.value not in SEMANTICS and e.value not in NON_PROPAGATING
    )
    assert undeclared == [], (
        f"these edge types propagate nothing and say nothing about why: {undeclared}. "
        f"Give them Semantics, or list them in NON_PROPAGATING with a reason."
    )


# ── the two planes cannot drift ───────────────────────────────────────────


def test_the_execution_plane_validates_the_contract_it_is_handed():
    """A versioned artefact nobody validates is an unversioned artefact.

    export_version went 2 → 3 and no reader noticed, because the execution
    plane read the file and trusted its shape.
    """
    qa = Path(__file__).resolve().parents[3] / "execution-plane" / "qa"
    if not qa.exists():  # pragma: no cover
        pytest.skip("execution plane not present")

    source = (qa / "orchestrator" / "context.py").read_text()
    assert "export_version" in source, (
        "the execution plane never checks export_version, so a schema change "
        "reaches it as wrong answers rather than as an error"
    )


# ── it has to work on a machine that has nothing ──────────────────────────


def test_a_fresh_clone_builds_without_any_credentials():
    """No .env, no token, no configuration — the platform must still start.

    This is not hypothetical. Deriving the change target from
    `code_intelligence_adapter`, which defaults to "github" whether or not
    anyone has pointed it anywhere, turned a fresh clone into a setup
    demanding a token it does not have. Sixteen tests passed on the machine
    that wrote the change and failed on a clean checkout — the same failure
    as arriving at a client and finding it does not run.
    """
    from app.adapters.registry import build_adapters
    from app.core.config import Settings

    bare = Settings(_env_file=None)
    assert bare.source_control_adapter == "local", (
        "a deployment that has been told nothing must not default into one that "
        "needs credentials"
    )
    build_adapters(bare, graph=None)


def test_deriving_still_happens_once_a_repository_is_named():
    """The fix must not disable the derivation it is protecting."""
    from app.core.config import Settings

    pointed = Settings(_env_file=None, code_index_repo="acme/widgets")
    assert pointed.source_control_adapter == "github"
    assert "source_control_adapter" in pointed.derived_keys


# ── the platform's namespace must not overlap the runner's ────────────────

# Set on every GitHub Actions runner. pydantic-settings binds by field name,
# so a field called `github_ref` reads GITHUB_REF whether anyone meant it to
# or not — and a control plane running inside Actions then configures itself
# from the ambient job rather than from its own settings.
RESERVED_BY_ACTIONS = {
    "GITHUB_ACTION", "GITHUB_ACTIONS", "GITHUB_ACTOR", "GITHUB_API_URL",
    "GITHUB_BASE_REF", "GITHUB_ENV", "GITHUB_EVENT_NAME", "GITHUB_EVENT_PATH",
    "GITHUB_GRAPHQL_URL", "GITHUB_HEAD_REF", "GITHUB_JOB", "GITHUB_OUTPUT",
    "GITHUB_PATH", "GITHUB_REF", "GITHUB_REF_NAME", "GITHUB_REF_PROTECTED",
    "GITHUB_REF_TYPE", "GITHUB_REPOSITORY", "GITHUB_REPOSITORY_OWNER",
    "GITHUB_RETENTION_DAYS", "GITHUB_RUN_ATTEMPT", "GITHUB_RUN_ID",
    "GITHUB_RUN_NUMBER", "GITHUB_SERVER_URL", "GITHUB_SHA",
    "GITHUB_STEP_SUMMARY", "GITHUB_WORKFLOW", "GITHUB_WORKFLOW_REF",
    "GITHUB_WORKFLOW_SHA", "GITHUB_WORKSPACE",
}

# GITHUB_TOKEN is not on a runner unless a workflow maps it there, and this
# platform's workflows map it deliberately. Reading it is the intent.
DELIBERATE_OVERLAP = {"GITHUB_TOKEN"}


def test_no_setting_reads_a_name_the_ci_runner_owns():
    """A field named `github_ref` reads GITHUB_REF whether anyone meant it or
    not. CI surfaced it as `refs/pull/1/merge`; in production a control plane
    hosted inside Actions would have dispatched against whatever branch
    happened to be building."""
    from pydantic import AliasChoices

    from app.core.config import Settings

    offenders = []
    for name, field in Settings.model_fields.items():
        alias = field.validation_alias
        if isinstance(alias, AliasChoices):
            names = {str(a).upper() for a in alias.choices}
        elif alias:
            names = {str(alias).upper()}
        else:
            names = {name.upper()}  # what pydantic-settings binds by default
        clash = (names & RESERVED_BY_ACTIONS) - DELIBERATE_OVERLAP
        if clash:
            offenders.append(f"{name} reads {sorted(clash)}")

    assert offenders == [], (
        "these settings are overwritten by the CI runner's own environment: "
        + "; ".join(offenders)
        + ". Give them a validation_alias outside the GITHUB_* namespace."
    )


def test_no_port_is_declared_and_never_used():
    """A Protocol nothing references is a seam that does not exist.

    DataShape sat in the execution plane's ports module unused: written,
    superseded by a method on the provider, and left behind. It then showed
    up in a generated port count as though it were a real seam — which is
    how an architecture diagram acquires an edge the codebase does not have.

    Scans the execution plane too. The factory invariant above only reads
    app/ports, so nothing was checking the other half of the platform.
    """
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    modules = list((root / "control-plane/api/app/ports").glob("*.py")) + list(
        (root / "execution-plane/qa/orchestrator").glob("ports*.py")
    )

    declared: dict[str, Path] = {}
    for path in modules:
        for node in _module_source(path).body:
            if isinstance(node, ast.ClassDef) and any(
                isinstance(b, ast.Name) and b.id == "Protocol" for b in node.bases
            ):
                declared[node.name] = path

    assert declared, "found no ports to check"

    searchable = [
        p
        for p in list((root / "control-plane/api/app").rglob("*.py"))
        + list((root / "execution-plane/qa/orchestrator").rglob("*.py"))
    ]
    corpus = "\n".join(p.read_text() for p in searchable)

    unused = sorted(
        name
        for name, path in declared.items()
        # One mention is its own declaration; a real port is referenced.
        if corpus.count(name) <= 1
    )
    assert unused == [], (
        f"these ports are declared and never referenced: {unused}. "
        f"Use them, or delete them — an unused Protocol is counted as a seam "
        f"by anything that enumerates the ports."
    )


def test_no_test_builds_settings_from_the_developers_own_env():
    """A suite that reads .env tests the machine it runs on.

    Twice now: deriving the change target from a bare default made 16 tests
    pass locally and fail on a clean checkout, and adding real JIRA_ keys
    made "refused without credentials" pass with credentials it was supposed
    to be missing. Opposite directions, same cause.
    """
    import ast
    from pathlib import Path

    tests = Path(__file__).resolve().parent
    offenders = []
    for path in sorted(tests.glob("test_*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if name != "Settings":
                continue
            supplied = {k.arg for k in node.keywords if k.arg}
            starred = any(k.arg is None for k in node.keywords)
            # A **dict may carry _env_file; those are checked by the dict
            # itself being isolated, which is visible at its definition.
            if "_env_file" not in supplied and not starred:
                offenders.append(f"{path.name}:{node.lineno}")

    assert offenders == [], (
        "these construct Settings without _env_file=None, so they read the "
        "developer's .env: " + ", ".join(offenders)
    )


# ── every adapter answers its whole port ──────────────────────────────────


def _adapters_for(port_module: str):
    """Concrete classes in the adapter package that mirrors a port module.

    Matched by directory name rather than by declared inheritance, because
    these are Protocols: an adapter that stopped satisfying one would not
    announce it by failing to subclass anything.
    """
    package = APP / "adapters" / port_module
    if not package.is_dir():
        return []
    found = []
    for path in sorted(package.glob("*.py")):
        if path.name.startswith("_"):
            continue
        module = importlib.import_module(f"app.adapters.{port_module}.{path.stem}")
        for _, obj in inspect.getmembers(module, inspect.isclass):
            if obj.__module__ == module.__name__:
                found.append(obj)
    return found


def _protocol_in(port_module: str):
    module = importlib.import_module(f"app.ports.{port_module}")
    for _, obj in inspect.getmembers(module, inspect.isclass):
        if getattr(obj, "_is_protocol", False) and obj.__module__ == module.__name__:
            return obj
    return None


@pytest.mark.parametrize(
    "port_module",
    sorted(
        p.stem
        for p in (APP / "ports").glob("*.py")
        if not p.stem.startswith("_")
        and (APP / "adapters" / p.stem).is_dir()
    ),
)
def test_every_adapter_implements_its_whole_port(port_module: str):
    """A method added to a Protocol that an adapter never grew.

    Protocols are structural, so nothing fails at import time — the gap
    surfaces as an AttributeError on the day that adapter is configured,
    which for a client-specific adapter is the day it is demonstrated. The
    graph port had exactly this: `phase_edges()` took a signature its own
    body contradicted and 392 tests passed, because no test ever built the
    real implementation.

    Parameter names are compared, not just arity: these are called with
    keywords across the codebase, so a renamed parameter is a break that
    positional-arity checking would wave through.
    """
    protocol = _protocol_in(port_module)
    if protocol is None:
        pytest.skip(f"no Protocol declared in app/ports/{port_module}.py")

    expected = {
        name: inspect.signature(getattr(protocol, name))
        for name in dir(protocol)
        if not name.startswith("_") and callable(getattr(protocol, name, None))
    }
    assert expected, f"{protocol.__name__} declares no methods"

    for adapter in _adapters_for(port_module):
        # Not everything in an adapter package implements the port — request
        # models, helpers and base classes live there too. An adapter is
        # something that answers at least one of the port's methods; a class
        # answering none of them is not claiming to be one.
        implemented = [n for n in expected if callable(getattr(adapter, n, None))]
        if not implemented:
            continue

        missing = sorted(set(expected) - set(implemented))
        assert not missing, (
            f"{adapter.__module__}.{adapter.__name__} implements "
            f"{len(implemented)}/{len(expected)} of {protocol.__name__} — "
            f"missing {missing}. Configure it and the phase calling a missing "
            f"method fails at run time, not here."
        )

        for name, want in expected.items():
            got = inspect.signature(getattr(adapter, name))
            want_params = [p for p in want.parameters if p != "self"]
            got_params = [p for p in got.parameters if p != "self"]
            assert got_params == want_params, (
                f"{adapter.__name__}.{name}{got} does not match "
                f"{protocol.__name__}.{name}{want} — these are called by "
                f"keyword, so a renamed parameter is a break"
            )
