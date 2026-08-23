"""The two phases run as separate CI jobs and communicate only through a
JSON state file. If that hand-off loses a field, the privileged job reports
on something other than what actually ran.
"""
from __future__ import annotations

import json

import pytest

from orchestrator import run as run_module


FINISHED_STATE = {
    "repo": "acme/demo",
    "pr_number": 7,
    "base_sha": "aaa",
    "head_sha": "bbb",
    "change_summary": "added a status filter",
    "affected_areas": ["/claims"],
    "test_plan": [{"id": "s1", "title": "filter by Approved", "type": "functional", "priority": "P1"}],
    "test_plan_gate_passed": True,
    "test_plan_attempts": 1,
    "test_assignments": [{"scenario_id": "s1", "mode": "generated", "file_path": "x.spec.ts"}],
    "generation_rejections": [],
    "evidence_summary": {"screenshot_count": 2, "trace_count": 2, "html_report": "evidence/html-report/index.html"},
    "gate_passed": True,
    "gate_reasons": ["all planned scenarios ran and passed"],
    "failing_scenarios": [],
}


def test_the_graph_compiles():
    from orchestrator.graph import build_graph

    assert build_graph() is not None


def test_state_survives_the_json_round_trip():
    assert json.loads(json.dumps(FINISHED_STATE)) == FINISHED_STATE


def _report(monkeypatch, capsys, tmp_path, state, argv_extra=()):
    state_file = tmp_path / "qa-state.json"
    state_file.write_text(json.dumps(state))
    monkeypatch.setenv("DRY_RUN", "1")
    monkeypatch.setattr("sys.argv", [
        "run", "--phase", "report", "--state-file", str(state_file),
        "--repo", "acme/demo", "--pr-number", "7", *argv_extra,
    ])
    code = run_module.main()
    return code, capsys.readouterr().out


def test_report_phase_reads_the_file_and_posts(monkeypatch, capsys, tmp_path):
    code, out = _report(monkeypatch, capsys, tmp_path, FINISHED_STATE)

    assert code == 0
    assert "Agentic QA — PASSED" in out
    assert "added a status filter" in out


def test_report_phase_needs_no_shas(monkeypatch, capsys, tmp_path):
    """The privileged job never computes a diff, so it must not require the
    commit range the run job was given."""
    code, _ = _report(monkeypatch, capsys, tmp_path, FINISHED_STATE)
    assert code == 0


def test_report_phase_exits_nonzero_when_the_gate_failed(monkeypatch, capsys, tmp_path):
    failed = {**FINISHED_STATE, "gate_passed": False,
              "failing_scenarios": ["filter by Approved"],
              "gate_reasons": ["1 test(s) failed"]}

    code, out = _report(monkeypatch, capsys, tmp_path, failed)

    assert code == 1
    assert "Agentic QA — FAILED" in out
    assert "Would file or update issue" in out


def test_missing_state_file_fails_loudly(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("DRY_RUN", "1")
    monkeypatch.setattr("sys.argv", [
        "run", "--phase", "report", "--state-file", str(tmp_path / "absent.json"),
        "--repo", "acme/demo", "--pr-number", "7",
    ])

    assert run_module.main() == 1
    assert "produced nothing to report" in capsys.readouterr().out


def test_run_phase_requires_a_state_file(monkeypatch):
    monkeypatch.setattr("sys.argv", [
        "run", "--phase", "run", "--repo", "acme/demo", "--pr-number", "7",
        "--base-sha", "a", "--head-sha", "b",
    ])
    with pytest.raises(SystemExit):
        run_module.main()


def test_run_phase_requires_commit_shas(monkeypatch, tmp_path):
    monkeypatch.setattr("sys.argv", [
        "run", "--phase", "run", "--repo", "acme/demo", "--pr-number", "7",
        "--state-file", str(tmp_path / "s.json"),
    ])
    with pytest.raises(SystemExit):
        run_module.main()
