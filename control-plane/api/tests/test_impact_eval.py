"""The harness that measures the blast radius.

Every number this platform quoted about impact was previously a property of
the code that produced it. These tests pin the scoring itself — a harness
that flatters the thing it measures is worse than no harness.
"""

from __future__ import annotations

from app.core.impact_eval import (
    Case,
    build_cases,
    directory_predictor,
    everything_predictor,
    graph_predictor,
    score,
)


KNOWN = {"app/a.py", "app/b.py", "app/c.py", "web/x.ts", "web/y.ts"}


# --- corpus construction ---------------------------------------------------


def test_each_file_in_a_commit_becomes_one_held_out_case():
    cases = build_cases({"c1": {"app/a.py", "app/b.py"}}, known_files=KNOWN)

    assert len(cases) == 2
    assert {c.seed for c in cases} == {"app/a.py", "app/b.py"}
    assert cases[0].expected == frozenset({"app/b.py"})


def test_a_single_file_commit_teaches_nothing_and_is_skipped():
    assert build_cases({"c1": {"app/a.py"}}, known_files=KNOWN) == []


def test_a_sweeping_commit_is_excluded_rather_than_kept():
    """Above roughly twenty files a commit is a rename sweep or a vendored
    update, where co-change carries no coupling signal and every predictor
    looks equally bad."""
    huge = {f"app/f{i}.py" for i in range(30)}
    assert build_cases({"c1": huge}, known_files=huge, max_files=20) == []


def test_files_the_graph_does_not_hold_are_dropped_not_scored_as_misses():
    """A commit touching a file since deleted asks the graph about something
    it has no node for. Scoring that as a miss measures history, not
    prediction."""
    cases = build_cases(
        {"c1": {"app/a.py", "app/b.py", "deleted/gone.py"}}, known_files=KNOWN
    )

    assert all("deleted/gone.py" not in c.expected for c in cases)
    assert {c.seed for c in cases} == {"app/a.py", "app/b.py"}


# --- scoring ---------------------------------------------------------------


def test_a_predictor_that_reaches_everything_expected_scores_full_recall():
    cases = [Case("c1", "app/a.py", frozenset({"app/b.py"}))]
    report = score("perfect", cases, lambda _seed: {"app/b.py"})

    assert (report.recall, report.precision, report.perfect) == (1.0, 1.0, 1)


def test_predicting_nothing_scores_zero_on_both_axes():
    cases = [Case("c1", "app/a.py", frozenset({"app/b.py"}))]
    report = score("empty", cases, lambda _seed: set())

    assert (report.recall, report.precision) == (0.0, 0.0)
    assert report.missed_everything == 1


def test_the_seed_itself_never_counts_as_a_prediction():
    """Predicting the file you were given is not a prediction."""
    cases = [Case("c1", "app/a.py", frozenset({"app/b.py"}))]
    report = score("lazy", cases, lambda seed: {seed, "app/b.py"})

    assert report.precision == 1.0


def test_recall_is_averaged_per_case_not_pooled():
    """One commit touching forty files must not dominate the figure that
    forty commits touching two files contributed to."""
    cases = [
        Case("small", "a", frozenset({"b"})),                       # 1/1 = 100%
        Case("large", "x", frozenset({f"y{i}" for i in range(10)})),  # 0/10 = 0%
    ]
    report = score("mixed", cases, lambda seed: {"b"} if seed == "a" else set())

    assert report.recall == 0.5      # pooled would give 1/11 = 9.1%


# --- predictors ------------------------------------------------------------


def test_the_graph_predictor_traverses_reverse_dependencies():
    dependents = {"app/a.py": {"app/b.py"}, "app/b.py": {"app/c.py"}}

    assert graph_predictor(dependents, depth=1)("app/a.py") == {"app/b.py"}
    assert graph_predictor(dependents, depth=2)("app/a.py") == {"app/b.py", "app/c.py"}


def test_the_directory_baseline_is_what_no_dependency_analysis_gives_you():
    """The bar the graph has to clear. If reverse traversal cannot beat
    'files in the same directory', it is not earning its complexity."""
    predict = directory_predictor(KNOWN)

    assert predict("app/a.py") == {"app/a.py", "app/b.py", "app/c.py"}
    assert predict("web/x.ts") == {"web/x.ts", "web/y.ts"}


def test_the_everything_baseline_gives_the_recall_column_a_ceiling():
    cases = [Case("c1", "app/a.py", frozenset({"web/y.ts"}))]
    report = score("everything", cases, everything_predictor(KNOWN))

    assert report.recall == 1.0
    assert report.precision < 0.3    # perfect recall, useless answer


def test_a_report_serialises_every_number_it_claims():
    cases = [Case("c1", "app/a.py", frozenset({"app/b.py"}))]
    payload = score("graph", cases, lambda _s: {"app/b.py"}).as_dict()

    assert set(payload) == {
        "predictor", "cases", "recall", "precision",
        "mean_radius_files", "complete_hits", "complete_misses",
    }
