"""What the run reports back for the platform to reconcile.

The control plane hands down a blast radius and compares it against this.
The comparison lives there, deliberately — a provider that graded its own
obligation would be marking its own homework — so what this plane owes is an
honest account of what it actually exercised.

`reports_coverage: True` in the adapter's capabilities is a promise. Before
these tests it was not kept: the pipeline emitted regression scope and
observed coverage but never `covered_modules`, so every obliged module came
back unaccounted and the reconciliation confidently reported a total failure
of coverage on a run that had covered everything.
"""

from __future__ import annotations

import pytest

from orchestrator.nodes.gate import _covered_modules


def _leaf(file: str, status: str = "expected") -> dict:
    return {"file": file, "status": status, "title": file}


def test_only_passing_specs_prove_coverage(monkeypatch):
    """A spec that ran and failed demonstrates the opposite of coverage.
    Counting it would let a broken change report its blast radius covered."""
    import orchestrator.nodes.gate as gate

    monkeypatch.setattr(gate, "_load_manifest", lambda: [], raising=False)
    state = {
        "observed_coverage": {
            "good.spec.ts": {"files": ["demo-app/app/claims/page.tsx"]},
            "bad.spec.ts": {"files": ["demo-app/app/api/claims/route.ts"]},
        },
        "test_assignments": [],
    }
    leaves = [_leaf("good.spec.ts"), _leaf("bad.spec.ts", "unexpected")]

    covered = _covered_modules(state, leaves)
    assert "demo-app/app/claims" in covered
    assert "demo-app/app/api/claims" not in covered


def test_a_spec_with_one_failing_case_proves_nothing(monkeypatch):
    """Even if its other cases passed. Partial success in a spec is not
    partial coverage of the module it exercised."""
    state = {
        "observed_coverage": {"mixed.spec.ts": {"files": ["demo-app/app/claims/page.tsx"]}},
        "test_assignments": [],
    }
    leaves = [_leaf("mixed.spec.ts"), _leaf("mixed.spec.ts", "unexpected")]
    assert _covered_modules(state, leaves) == []


def test_observation_is_preferred_to_the_manifests_claim(monkeypatch):
    """`covers_modules` is somebody's assertion; the files a spec actually
    requested are the run's own account. Where both exist, the second wins —
    otherwise a stale manifest entry launders itself into evidence."""
    import orchestrator.nodes.gate as gate

    monkeypatch.setattr(
        gate,
        "_load_manifest",
        lambda: [{"id": "s1", "covers_modules": ["demo-app/app/api/claims"]}],
        raising=False,
    )
    state = {
        # The run says it touched the page, not the route the manifest claims.
        "observed_coverage": {"s1.spec.ts": {"files": ["demo-app/app/claims/page.tsx"]}},
        "test_assignments": [
            {"source_script_id": "s1", "file_path": "/tmp/x/s1.spec.ts"}
        ],
    }
    covered = _covered_modules(state, [_leaf("s1.spec.ts")])
    assert covered == ["demo-app/app/claims"]


def test_the_manifest_is_the_fallback_when_a_run_produced_no_trace():
    """A run with tracing off still has to report something, and the
    manifest's claim for a script that demonstrably passed is a weaker but
    real answer. The alternative is reporting zero coverage for a run that
    covered plenty, which the reconciliation would read as a refusal."""
    state = {
        "observed_coverage": {},
        "test_assignments": [
            {"source_script_id": "claims-list-renders", "file_path": "/t/claims-list.spec.ts"}
        ],
    }
    covered = _covered_modules(state, [_leaf("claims-list.spec.ts")])
    assert covered  # from the real manifest this repo ships


def test_a_failed_script_gets_no_fallback_either():
    state = {
        "observed_coverage": {},
        "test_assignments": [
            {"source_script_id": "claims-list-renders", "file_path": "/t/claims-list.spec.ts"}
        ],
    }
    assert _covered_modules(state, [_leaf("claims-list.spec.ts", "unexpected")]) == []


def test_the_gate_puts_both_lists_in_the_state_the_platform_reads():
    """The end the control plane actually consumes. Without these keys the
    adapter's reports_coverage promise is broken silently."""
    from orchestrator.nodes import gate

    state = gate.run(
        {
            "run_results_raw": {"suites": []},
            "test_plan": [],
            "test_assignments": [],
            "regression_scope": {"uncovered_components": ["demo-app/app/blog"]},
            "observed_coverage": {},
        }
    )
    assert "covered_modules" in state
    assert state["uncovered_modules"] == ["demo-app/app/blog"]
