"""Selection is a decision, not an intersection.

It used to be arithmetic: any script whose declared covers_modules met the
impacted set. Pointed at Fronei that returned the whole library for every
change — two scripts, both declaring broad shared modules, and almost any
edit touches one. The framework's claim is that it is frugal with execution,
and running everything every time is not frugality with extra steps.
"""

from __future__ import annotations

from orchestrator.selection import select

TRUSTED = {"generated": True, "commit_sha": "abc1234", "internal_capture_rate": 0.99}

# Declared narrowly here so the declaration path is actually exercised.
# Fronei's real manifest declares both scripts against the shared modules,
# which is precisely why intersection selected everything there.
LIBRARY = [
    {"id": "admin", "covers_files": ["app/admin/page.tsx"], "covers_modules": ["app/admin"]},
    {
        "id": "workbench",
        "covers_files": ["app/components/Shell.tsx"],
        "covers_modules": ["app/components"],
    },
]

OBSERVED = {"admin": {"app/admin/page.tsx"}, "workbench": {"app/components/Shell.tsx"}}


def _impact(**over):
    return {"affected": ["x"], "changed": [], "test_obligations": [], **over}


# ── narrowing, once it is earned ──────────────────────────────────────────


def test_observation_licenses_an_exclusion():
    out = select(
        LIBRARY,
        _impact(changed=["app/components/Shell.tsx"]),
        provenance=TRUSTED, head_sha="abc1234", observed=OBSERVED,
    )
    assert out.strategy == "targeted"
    assert out.scripts == ["workbench"]
    assert out.skipped[0]["script"] == "admin"


def test_a_declaration_does_not():
    """Including on a hand-written claim is safe — the worst case is running
    something unnecessary. Excluding on one is a bet that the claim is
    complete, and losing it means a regression nobody ran the test for."""
    out = select(
        LIBRARY,
        _impact(changed=["app/components/Shell.tsx"]),
        provenance=TRUSTED, head_sha="abc1234",
    )
    assert set(out.scripts) == {"admin", "workbench"}
    assert any("for want of observed coverage" in s["why"] for s in out.skipped)


def test_reach_alone_obliges_nothing():
    """A relationship can propagate impact without obliging a scenario.
    Requiring a regression run for a deployment edge is how a required set
    becomes something teams learn to ignore."""
    out = select(
        LIBRARY, _impact(affected=["app/admin/page.tsx"]),
        provenance=TRUSTED, head_sha="abc1234", observed=OBSERVED,
    )
    assert out.scripts == []


# ── and escalating, when narrowing cannot be trusted ──────────────────────


def test_no_assessment_runs_everything():
    out = select(LIBRARY, None, provenance=TRUSTED, head_sha="abc1234")
    assert out.strategy == "full"
    assert set(out.scripts) == {"admin", "workbench"}


def test_a_graph_describing_another_commit_runs_everything():
    out = select(
        LIBRARY, _impact(changed=["app/components/Shell.tsx"]),
        provenance=TRUSTED, head_sha="deadbee", observed=OBSERVED,
    )
    assert out.strategy == "full"
    assert any("describes abc1234" in r for r in out.reasons)


def test_a_thin_index_runs_everything():
    out = select(
        LIBRARY, _impact(changed=["app/components/Shell.tsx"]),
        provenance={**TRUSTED, "internal_capture_rate": 0.4},
        head_sha="abc1234", observed=OBSERVED,
    )
    assert out.strategy == "full"


def test_files_the_graph_never_heard_of_run_everything():
    """The graph cannot say what an unknown file reaches, and an exclusion
    computed without it is an exclusion computed without the change."""
    out = select(
        LIBRARY,
        _impact(changed=["app/components/Shell.tsx"], unmapped=["app/new-thing.ts"]),
        provenance=TRUSTED, head_sha="abc1234", observed=OBSERVED,
    )
    assert out.strategy == "full"


# ── the bug escalation introduced ─────────────────────────────────────────


def test_a_change_touching_nothing_runs_nothing_even_unassessed():
    """Editing a README escalated to the entire regression library: with no
    assessment to narrow with, "cannot be trusted to exclude" fired on a
    change there was nothing to exclude from. Escalation is for a change with
    something to test and no reliable way to scope it."""
    out = select(LIBRARY, None, provenance=TRUSTED, head_sha="abc1234",
                 touches_indexed_scope=False)
    assert out.strategy == "none"
    assert out.scripts == []


def test_an_empty_library_is_not_an_error():
    out = select([], _impact(), provenance=TRUSTED, head_sha="abc1234")
    assert out.strategy == "none"


def test_the_argument_travels_with_the_answer():
    """A regression suite that quietly shrank is indistinguishable from one
    that was quietly disabled."""
    out = select(
        LIBRARY, _impact(changed=["app/components/Shell.tsx"]),
        provenance=TRUSTED, head_sha="abc1234", observed=OBSERVED,
    )
    assert out.reasons and out.skipped and out.obliged_files
