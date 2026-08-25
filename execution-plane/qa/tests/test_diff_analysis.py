"""Which files a change touched.

Deterministic on purpose: this is the input to blast-radius scoping, so
asking a model for it would make regression scope depend on a summary. These
tests pin the cases the previous diff-header parse got wrong.
"""

from __future__ import annotations

from orchestrator.nodes.diff_analysis import (
    changed_paths,
    changed_paths_from_name_status,
)


def _records(*fields: str) -> str:
    return "\0".join(fields) + "\0"


def test_a_plain_modification_is_read():
    raw = _records("M", "demo-app/app/claims/page.tsx")
    assert changed_paths_from_name_status(raw) == ["demo-app/app/claims/page.tsx"]


def test_added_and_deleted_files_both_count():
    """A deletion is a change its dependents have to survive."""
    raw = _records("A", "demo-app/new.ts", "D", "demo-app/gone.ts")
    assert changed_paths_from_name_status(raw) == ["demo-app/gone.ts", "demo-app/new.ts"]


def test_a_rename_is_scoped_to_the_new_path():
    """The bug this exists to catch. `diff --git a/old b/new` names the
    pre-rename path first, so the header parse scoped regression to a file
    that no longer exists — and tested nothing."""
    raw = _records("R100", "demo-app/old-name.tsx", "demo-app/new-name.tsx")

    assert changed_paths_from_name_status(raw) == ["demo-app/new-name.tsx"]


def test_a_copy_counts_both_source_and_destination():
    """The source is unchanged, but the copy is new code that nothing covers."""
    raw = _records("C75", "demo-app/original.ts", "demo-app/copy.ts")
    assert changed_paths_from_name_status(raw) == [
        "demo-app/copy.ts",
        "demo-app/original.ts",
    ]


def test_a_path_containing_a_space_survives_intact():
    """NUL separation is the point: the header parse used `\\S+` and truncated
    at the first space, producing a path that matches nothing."""
    raw = _records("M", "demo-app/app/my components/Table.tsx")
    assert changed_paths_from_name_status(raw) == ["demo-app/app/my components/Table.tsx"]


def test_empty_output_is_no_paths_not_an_error():
    assert changed_paths_from_name_status("") == []


def test_a_trailing_partial_record_does_not_crash():
    assert changed_paths_from_name_status(_records("M")) == []


def test_the_header_fallback_still_works_for_a_plain_diff():
    diff = (
        "diff --git a/demo-app/app/claims/page.tsx b/demo-app/app/claims/page.tsx\n"
        "index 1..2 100644\n"
    )
    assert changed_paths(diff) == ["demo-app/app/claims/page.tsx"]


def test_the_header_fallback_is_documented_as_wrong_on_renames():
    """Kept as a fallback, and this pins why it is only that: it reports the
    path the rename moved away from."""
    diff = "diff --git a/demo-app/old.tsx b/demo-app/new.tsx\nsimilarity index 100%\n"
    assert changed_paths(diff) == ["demo-app/old.tsx"]
