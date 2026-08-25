"""Shared state that flows through every node in the QA pipeline graph.

This is the work-graph context object for this one phase (QA). Every node
reads what it needs and writes its own section — nothing is inferred
silently between nodes.
"""
from __future__ import annotations

from typing import Any, TypedDict


class Scenario(TypedDict, total=False):
    id: str
    title: str
    type: str  # functional | regression | edge-case | negative
    target_route: str
    expected_outcome: str
    priority: str  # P1 | P2 | P3
    confidence: str  # high | medium | low
    ac_ref: str


class TestAssignment(TypedDict, total=False):
    scenario_id: str
    mode: str  # "selected" | "generated" | "required-regression"
    file_path: str
    source_script_id: str | None


class PipelineState(TypedDict, total=False):
    # --- intake ---
    repo: str
    pr_number: int
    base_sha: str
    head_sha: str
    diff_text: str
    features_context: dict[str, Any]

    # --- phase 1: diff analysis ---
    change_summary: str
    affected_areas: list[str]
    changed_paths: list[str]
    regression_scope: dict[str, Any]

    # --- phase 2: test plan ---
    test_plan: list[Scenario]
    test_plan_gate_passed: bool
    test_plan_gate_reasons: list[str]
    test_plan_attempts: int

    # --- phase 3: test data ---
    seed_summary: str
    seed_file: str

    # --- phase 4: test generation / selection ---
    test_assignments: list[TestAssignment]
    generation_rejections: list[str]
    required_assignments: list[str]

    # --- phase 5: execution ---
    run_exit_code: int
    run_results_raw: dict[str, Any]
    # Whether this run had to give up parallelism, and why.
    ran_serially: bool
    mutating_specs: dict[str, list[str]]
    data_store_mutated: bool

    # --- phase 6: evidence ---
    evidence_summary: dict[str, Any]
    # What each spec was observed to exercise, from its trace. The measured
    # counterpart to the manifest's declared covers_modules.
    observed_coverage: dict[str, Any]
    coverage_mismatches: list[str]
    coverage_gaps_observed: dict[str, Any]
    # Generated specs worth keeping. Proposed here, applied elsewhere:
    # this job holds no write token, by design.
    promotion_candidates: list[dict[str, Any]]

    # --- context graph ---
    assertions: list[dict[str, Any]]

    # --- phase 7: gate ---
    gate_passed: bool
    gate_reasons: list[str]
    failing_scenarios: list[str]
    # What the blast radius obliged this run to re-test, and how that went.
    required_regressions: list[str]
    required_regressions_failed: list[str]
    required_regressions_missing: list[str]
    coverage_gaps: list[str]
    # Reasons to qualify the scoping — a stale or unpinned code graph.
    graph_warnings: list[str]

    # --- phase 8: report ---
    defects_created: list[str]
    pr_comment_url: str | None
