"""Enforces deterministic-core purity as a real regression test, not just a
comment: none of these modules may import `anthropic`, directly or
transitively. Each check runs in a clean subprocess (not modulefinder's
static trace) so a module already imported earlier in the same test session
by another test can't produce a false negative.
"""

import subprocess
import sys

import pytest

FORBIDDEN_MODULES = [
    "app.core.config",
    "app.core.db",
    "app.core.audit",
    "app.core.confidence",
    "app.core.gate_controller",
    "app.core.reliability",
    "app.ports.requirements_source",
    "app.ports.code_design_context",
    "app.ports.test_management",
    "app.ports.build_deploy",
    "app.ports.llm_provider",
    "app.ports.audit_sink",
    "app.ports.work_dispatch",
    "app.core.dispatches",
    "app.core.context_graph",
    "app.graph.ontology",
    "app.graph.identity",
    "app.ports.entity_resolver",
    "app.models.graph",
    "app.core.reconciler",
    "app.models.dispatch",
    "app.agents.graph",
    "app.agents.state",
    "app.agents.nodes",
    "app.models.base",
    "app.models.run",
    "app.models.audit_log",
    "app.routers.health",
    "app.routers.runs",
]


@pytest.mark.parametrize("module_name", FORBIDDEN_MODULES)
def test_module_never_imports_anthropic(module_name: str) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            f"import {module_name}; import sys; assert 'anthropic' not in sys.modules, "
            f"'{module_name} transitively imported anthropic'",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"{module_name}: {result.stderr}"


def test_claude_adapter_is_the_only_anthropic_importer() -> None:
    result = subprocess.run(
        ["grep", "-rl", "^import anthropic\\|^from anthropic", "app"],
        capture_output=True,
        text=True,
        cwd=__file__.rsplit("/tests/", 1)[0],
    )
    files = [f for f in result.stdout.strip().splitlines() if f]
    assert files == ["app/adapters/llm/claude_adapter.py"], files


def test_only_the_github_adapter_speaks_http() -> None:
    """The same rule the Claude adapter is held to, applied to the new port.

    A CI client reachable from the core is how "pluggable" quietly becomes
    "GitHub-shaped" — someone needs a run URL in a hurry and imports httpx
    where it is convenient rather than where it belongs.
    """
    result = subprocess.run(
        ["grep", "-rl", "^import httpx\\|^from httpx", "app"],
        capture_output=True,
        text=True,
        cwd=__file__.rsplit("/tests/", 1)[0],
    )
    files = [f for f in result.stdout.strip().splitlines() if f]
    assert files == ["app/adapters/work_dispatch/github_actions.py"], files


@pytest.mark.parametrize(
    "module_name",
    ["app.core.dispatches", "app.core.reconciler", "app.agents.nodes", "app.core.context_graph"],
)
def test_core_never_imports_a_work_dispatch_adapter(module_name: str) -> None:
    """The core may depend on the port, never on a concrete CI system."""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            f"import {module_name}; import sys; "
            f"assert not any(m.startswith('app.adapters.work_dispatch') for m in sys.modules), "
            f"'{module_name} pulled in a work_dispatch adapter'",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"{module_name}: {result.stderr}"
