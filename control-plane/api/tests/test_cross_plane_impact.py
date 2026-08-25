"""The two planes must answer the same question the same way.

They did not. The design gate traversed files two hops and rolled up; the
execution plane traversed modules one hop over the rollup. On
apps/web/app/lib/format.ts the gate reported a change reaching app/app that
QA never required a test for, while QA required app/blog the gate never
named — so a change could pass a containment check and then be tested
against a different set.

One engine fixed the semantics. This is what stops them separating again:
it runs the real execution-plane function, against the real export shape,
and compares it with the control plane's assessment.
"""

import json
import sys
from pathlib import Path

import pytest

from app.core.design_review import assess_change
from app.core.graph_export import EXPORT_VERSION
from app.core.impact import ENGINE_VERSION, Policy, roll_up

QA_ROOT = Path(__file__).resolve().parents[3] / "execution-plane" / "qa"


@pytest.fixture
def qa_context(tmp_path, monkeypatch):
    """The execution plane's own module, loaded against a fixture export."""
    if not QA_ROOT.exists():  # pragma: no cover - only in a partial checkout
        pytest.skip("execution plane not present")

    graph = {
        "export_version": EXPORT_VERSION,
        "project": "default",
        "scope": "",
        "generated": True,
        "provenance": {"commit_sha": "abc1234"},
        "impact": {"engine_version": ENGINE_VERSION, "policy": Policy().as_dict()},
        "modules": [
            {"id": "app/lib", "paths": ["app/lib/format.ts", "app/lib/api.ts"]},
            {"id": "app/components", "paths": ["app/components/Card.tsx"]},
            {"id": "app/blog", "paths": ["app/blog/page.tsx"]},
            {"id": "app/admin", "paths": ["app/admin/page.tsx"]},
        ],
        # target -> files that import it
        "file_dependents": {
            "app/lib/format.ts": ["app/components/Card.tsx"],
            "app/components/Card.tsx": ["app/blog/page.tsx", "app/admin/page.tsx"],
        },
        "depends_on": [
            {"from": "app/components", "to": "app/lib", "weight": 1},
            {"from": "app/blog", "to": "app/components", "weight": 1},
            {"from": "app/admin", "to": "app/components", "weight": 1},
        ],
        "routes": {},
    }
    path = tmp_path / "code-graph.json"
    path.write_text(json.dumps(graph))

    monkeypatch.setenv("QA_CODE_GRAPH", str(path))
    sys.path.insert(0, str(QA_ROOT))
    for name in [m for m in sys.modules if m.startswith("orchestrator")]:
        del sys.modules[name]
    try:
        from orchestrator import context

        yield context, graph
    finally:
        sys.path.remove(str(QA_ROOT))
        for name in [m for m in sys.modules if m.startswith("orchestrator")]:
            del sys.modules[name]


def _control_plane_modules(graph: dict, changed: list[str]) -> list[str]:
    file_dependents = {k: set(v) for k, v in graph["file_dependents"].items()}
    p2m = {p: m["id"] for m in graph["modules"] for p in m["paths"]}
    out = assess_change(changed, file_dependents)
    return roll_up(out.changed + out.affected, p2m)


@pytest.mark.parametrize(
    "changed",
    [
        ["app/lib/format.ts"],
        ["app/components/Card.tsx"],
        ["app/lib/api.ts"],
        ["app/lib/format.ts", "app/blog/page.tsx"],
    ],
)
def test_both_planes_reach_the_same_modules(qa_context, changed):
    context, graph = qa_context

    direct = context.modules_for_paths(changed)
    qa_modules = sorted(context.blast_radius(direct, changed))
    control_modules = sorted(_control_plane_modules(graph, changed))

    assert qa_modules == control_modules, (
        f"the planes disagree about {changed}: "
        f"QA says {qa_modules}, the design gate says {control_modules}"
    )


def test_the_execution_plane_reads_the_exported_depth(qa_context):
    """Not a constant of its own. A depth changed in one place and not the
    other is the same defect wearing a different hat."""
    context, _ = qa_context
    assert context.impact_policy()["max_depth"] == Policy().max_depth
    assert context.impact_policy()["engine_version"] == ENGINE_VERSION


def test_without_file_edges_it_falls_back_and_is_coarser(qa_context, tmp_path, monkeypatch):
    """An older export has no file edges. Falling back to the module rollup
    is coarser, which is a worse answer and not a wrong one — the failure to
    avoid is pretending."""
    context, graph = qa_context
    stripped = {**graph, "file_dependents": {}}
    path = tmp_path / "old-graph.json"
    path.write_text(json.dumps(stripped))
    monkeypatch.setattr(context, "CODE_GRAPH_FILE", path)
    context._load_code_graph.cache_clear() if hasattr(context._load_code_graph, "cache_clear") else None

    direct = context.modules_for_paths(["app/lib/format.ts"])
    assert context.blast_radius(direct, ["app/lib/format.ts"]) >= direct
