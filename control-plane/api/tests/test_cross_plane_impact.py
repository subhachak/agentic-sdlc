"""The two planes must answer the same question the same way.

They did not. The design gate traversed files two hops and rolled up; the
execution plane traversed modules one hop over the rollup. On
apps/web/app/lib/format.ts the gate reported a change reaching app/app that
QA never required a test for, while QA required app/blog the gate never
named — so a change could pass a containment check and then be tested
against a different set.

One engine fixed the semantics, and then the execution plane stopped
traversing at all: reach is decided once, by app/core/impact.py, and travels
with the request. Two implementations that agree today agree for reasons
neither of them states — measured across 46 real commits, the agreement held
only because the graph carries one edge type and an IMPORTS path stays above
the confidence floor for nine hops while the policy stops at two.

So this file no longer compares two traversals. It checks the handover: that
what the execution plane scopes against is what the control plane assessed,
and that a plane given nothing says so instead of inventing a walk.
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
    """Handed the assessment, the execution plane scopes to exactly what the
    control plane assessed — no widening of its own, no narrowing."""
    context, graph = qa_context

    file_dependents = {k: set(v) for k, v in graph["file_dependents"].items()}
    assessment = assess_change(changed, file_dependents)

    qa_modules = sorted(context.impacted_modules(changed, assessment.as_dict()))
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


def test_with_no_assessment_it_narrows_and_says_so(qa_context):
    """The one thing it must not do is guess.

    A walk invented here is the duplicate that was just deleted, and it would
    come back with nobody deciding to bring it back. So an unassessed run
    scopes to the directly changed modules — and warns, loudly, because the
    unsafe direction is the narrow one: fewer required regressions is a run
    that passes more easily and looks cleaner rather than smaller.
    """
    context, _ = qa_context
    changed = ["app/lib/format.ts"]

    assert context.impacted_modules(changed, None) == context.modules_for_paths(changed)
    assert context.impacted_modules(changed, {"affected": []}) == context.modules_for_paths(changed)

    scope = context.regression_candidates(changed)
    assert any(
        "no impact assessment was supplied" in w for w in scope["graph_warnings"]
    )


def test_an_assessment_widens_beyond_the_changed_modules(qa_context):
    """The counterpart: given one, scope is genuinely wider than the edit."""
    context, graph = qa_context
    changed = ["app/lib/format.ts"]
    file_dependents = {k: set(v) for k, v in graph["file_dependents"].items()}

    widened = context.impacted_modules(changed, assess_change(changed, file_dependents).as_dict())
    assert widened > context.modules_for_paths(changed)
