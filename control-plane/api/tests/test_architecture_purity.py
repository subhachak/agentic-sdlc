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
