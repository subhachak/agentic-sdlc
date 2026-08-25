"""One repository, and the fields that follow from it.

There were three repository fields — the one to index, the one changes are
proposed against, and the one holding the CI workflow — plus a ref each. In
almost every deployment they are the same value typed three times, and the
console asked for all six. The three that genuinely differ are the
interesting case, not the default.
"""

import pytest

from app.core import projects, settings_store
from app.core.config import Settings, derive


def mk(**kw) -> Settings:
    # No env file: this repository has a populated .env, and a test that
    # reads it is testing the machine rather than the code.
    return Settings(_env_file=None, **kw)


def test_one_repository_answers_all_three():
    s = mk(code_index_repo="acme/widgets")
    assert s.target_repo == "acme/widgets"
    assert s.github_repo == "acme/widgets"
    assert {"target_repo", "github_repo"} <= s.derived_keys


def test_an_explicit_value_wins():
    """The uncommon layouts are why these can be set at all."""
    s = mk(code_index_repo="acme/widgets", github_repo="acme/ci")
    assert s.github_repo == "acme/ci"
    assert "github_repo" not in s.derived_keys


def test_a_ref_follows_the_repository_it_belongs_to():
    s = mk(code_index_repo="acme/widgets", code_index_ref="develop")
    assert s.target_ref == "develop"
    assert s.github_ref == "develop"


def test_a_ref_does_not_cross_to_a_different_repository():
    """A base branch from one repository is not a fact about another."""
    s = mk(code_index_repo="acme/widgets", code_index_ref="develop", github_repo="acme/ci")
    assert s.github_ref == "main"


def test_nothing_configured_derives_nothing():
    s = mk()
    assert s.derived_keys == frozenset()
    assert s.target_repo is None


def test_the_export_scope_is_not_guessed():
    """It defaulted to the sample app's name, so pointing the platform at any
    real repository failed with an error blaming the index."""
    assert mk().qa_export_scope == ""


# --- the project overlay ------------------------------------------------


def record(**engagement) -> projects.ProjectRecord:
    return projects.ProjectRecord(
        id="team-a", name="", description="", engagement=engagement, archived=False
    )


def test_a_projects_repository_redirects_the_derived_fields():
    """model_copy does not re-run validators, so without an explicit derive
    the fields would still name the previous project's repository."""
    base = mk(code_index_repo="acme/widgets")
    assert base.target_repo == "acme/widgets"

    applied = projects.applied_to(base, record(code_index_repo="other/thing"))
    assert applied.target_repo == "other/thing"
    assert applied.github_repo == "other/thing"


def test_a_project_may_still_override_a_derived_field():
    applied = projects.applied_to(
        mk(code_index_repo="acme/widgets"),
        record(code_index_repo="other/thing", target_repo="other/fork"),
    )
    assert applied.target_repo == "other/fork"
    assert applied.github_repo == "other/thing"


def test_resetting_a_derived_field_restores_its_default_not_none():
    """Blanking to None nulled a default derivation could not refill."""
    applied = projects.applied_to(mk(), record(target_environment="prod"))
    assert applied.target_ref == "main"


# --- what the console is told -------------------------------------------


def test_describe_reports_what_is_in_force_not_the_environment():
    """The page showed the value before the active project was applied, so a
    repository set for a project read as unset."""
    base = mk()
    live = projects.applied_to(base, record(code_index_repo="acme/widgets"))
    entries = {e["key"]: e for e in settings_store.describe(base, {}, live)}

    assert entries["code_index_repo"]["value"] == "acme/widgets"
    assert entries["target_repo"]["value"] == "acme/widgets"
    assert entries["target_repo"]["derived"] is True
    assert entries["target_repo"]["derived_from"] == "code_index_repo"


def test_operations_owned_fields_are_marked_so_two_pages_cannot_disagree():
    entries = {e["key"]: e for e in settings_store.describe(mk(), {})}
    for key in ("code_index_repo", "code_index_ref", "qa_export_scope"):
        assert entries[key]["owned_by"] == "operations", key


@pytest.mark.parametrize(
    "key,adapter_key,needs",
    [
        ("target_working_copy", "source_control_adapter", "local"),
        ("code_index_local_root", "code_intelligence_adapter", "local"),
        ("github_workflow_file", "work_dispatch_adapter", "github-actions"),
    ],
)
def test_a_field_another_setting_makes_meaningless_is_not_asked(key, adapter_key, needs):
    on = {e["key"]: e for e in settings_store.describe(mk(**{adapter_key: needs}), {})}
    assert on[key]["relevant"] is True

    other = "github" if needs == "local" else "local"
    off = {e["key"]: e for e in settings_store.describe(mk(**{adapter_key: other}), {})}
    assert off[key]["relevant"] is False
