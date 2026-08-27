"""Debt is declared, and the declaration may not grow.

The differential gate stops a red suite refusing every change, which is what
makes the platform installable. On its own it is also a permanent excuse: the
pre-existing list can grow forever and nothing notices, so attribution
quietly becomes tolerance and the suite rots at exactly the speed nobody is
measuring.

This is what makes the permissive default self-tightening. A test that starts
failing has to be fixed or written down, and writing it down is a commit
somebody reviews. That review is the mechanism — the file is what makes the
tolerance visible, and without it the gate is tolerant in private.
"""

from __future__ import annotations

import json

from orchestrator.known_failing import Ratchet, assess, load

BASE_RED = {"admin": "failed", "workbench": "failed", "blog": "passed"}


def test_declared_debt_is_honoured():
    out = assess(BASE_RED, {"admin", "workbench"})
    assert out.honoured == ["admin", "workbench"]
    assert out.blocking == []


def test_debt_nobody_wrote_down_blocks():
    """A failure merged without being recorded is the growth this exists to
    stop. It failed before this change, so it is not this change's
    regression — but admitting it has to be somebody's decision."""
    out = assess(BASE_RED, {"admin"})
    assert out.grew == ["workbench"]
    assert out.blocking == ["workbench"]


def test_debt_can_only_be_paid_down():
    """The record shrinking is the only direction it moves without a human."""
    out = assess({"admin": "passed"}, {"admin"})
    assert out.stale == ["admin"]
    assert out.blocking == []


def test_the_proposal_never_launders_new_failures():
    """The pipeline offers a record to adopt. If that record included the
    growth, the ratchet would hand teams a one-click way to accept exactly
    what it just refused."""
    out = assess(BASE_RED, {"admin"})
    assert "workbench" in out.grew
    assert "workbench" not in out.proposal
    assert out.proposal == ["admin"]


# ── adoption, and the two ways to get it wrong ────────────────────────────


def test_no_record_is_not_an_empty_record():
    """"Not yet adopted" is not "nothing may fail". The second refuses every
    change to the very codebases the differential exists to make adoptable,
    which is how a control gets switched off in week one."""
    out = assess(BASE_RED, None)
    assert out.established is False
    assert out.blocking == []
    assert out.proposal == ["admin", "workbench"]


def test_an_unreadable_record_is_no_record_rather_than_a_guess(tmp_path):
    bad = tmp_path / "known-failing.json"
    bad.write_text("{ not json")
    assert load(bad) is None

    absent = tmp_path / "nope.json"
    assert load(absent) is None


def test_a_record_is_read_in_either_shape(tmp_path):
    wrapped = tmp_path / "a.json"
    wrapped.write_text(json.dumps({"known_failing": ["admin"]}))
    bare = tmp_path / "b.json"
    bare.write_text(json.dumps(["admin"]))
    assert load(wrapped) == load(bare) == {"admin"}


# ── the destination ───────────────────────────────────────────────────────


def test_strict_mode_admits_no_debt_at_all():
    """For a suite that is green and intends to stay that way. The ratchet's
    destination, available immediately to anyone already there."""
    out = assess(BASE_RED, {"admin", "workbench"}, strict=True)
    assert out.blocking == ["admin", "workbench"]
    assert out.honoured == []


def test_strict_mode_ignores_the_record_entirely():
    """Otherwise a project could reach "green" by writing its failures down,
    which is the opposite of what the setting asks for."""
    assert assess(BASE_RED, {"admin", "workbench"}, strict=True).blocking == [
        "admin",
        "workbench",
    ]
    assert assess(BASE_RED, None, strict=True).blocking == ["admin", "workbench"]


def test_a_green_baseline_passes_strict_mode():
    assert assess({"admin": "passed"}, None, strict=True).blocking == []


# ── and it reaches the verdict ────────────────────────────────────────────


def _gate(tmp_path, monkeypatch, declared, *, strict=False, baseline=None):
    """The gate, run against a record on disk."""
    import importlib
    from tests.test_differential_gate import _state

    record = tmp_path / "known-failing.json"
    if declared is not None:
        record.write_text(json.dumps({"known_failing": declared}))
    monkeypatch.setenv("QA_KNOWN_FAILING", str(record))
    monkeypatch.setenv("QA_REQUIRE_GREEN_BASELINE", "1" if strict else "")

    import orchestrator.paths
    import orchestrator.nodes.gate as gate

    importlib.reload(orchestrator.paths)
    importlib.reload(gate)
    out = gate.run(
        _state(baseline_verdicts=baseline or {"admin-overview": "failed"})
    )
    importlib.reload(orchestrator.paths)
    importlib.reload(gate)
    return out


def test_a_declared_failure_still_lets_the_change_through(tmp_path, monkeypatch):
    out = _gate(tmp_path, monkeypatch, ["admin-overview"])
    assert out["gate_passed"] is True
    assert out["known_failing"]["honoured"] == ["admin-overview"]


def test_an_undeclared_failure_stops_it_and_says_what_to_do(tmp_path, monkeypatch):
    out = _gate(tmp_path, monkeypatch, [])
    assert out["gate_passed"] is False
    assert out["known_failing"]["grew"] == ["admin-overview"]
    assert any("never written down" in r for r in out["gate_reasons"])
    # The instruction matters as much as the refusal: a gate that blocks
    # without naming the remedy is one people route around.
    assert any("known-failing.json" in r for r in out["gate_reasons"])


def test_without_a_record_it_offers_one_rather_than_writing_it(tmp_path, monkeypatch):
    """A pipeline that recorded its own accepted failures would ratchet the
    wrong way on its first run and call it a baseline."""
    out = _gate(tmp_path, monkeypatch, None)
    assert out["gate_passed"] is True
    assert out["known_failing"]["established"] is False
    assert any("would start the ratchet" in r for r in out["gate_reasons"])
    assert not (tmp_path / "known-failing.json").exists()


def test_strict_mode_refuses_declared_debt_too(tmp_path, monkeypatch):
    out = _gate(tmp_path, monkeypatch, ["admin-overview"], strict=True)
    assert out["gate_passed"] is False
