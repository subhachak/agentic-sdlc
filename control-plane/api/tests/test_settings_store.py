"""Configuration through the control plane.

The rules that matter here are about what must *not* be possible: writing a
secret through the API, changing something the process is built around, or
setting an adapter to a value no adapter implements.
"""

from __future__ import annotations

import pytest

from app.core.config import Settings
from app.core.settings_store import (
    BY_KEY,
    MUTABLE_KEYS,
    SPECS,
    ConfigError,
    describe,
    effective,
    validate,
)


def _base(**kwargs) -> Settings:
    return Settings(_env_file=None, **kwargs)


# --- what may be changed ---------------------------------------------------


def test_a_mutable_override_takes_effect():
    settings = effective(_base(llm_provider_adapter="mock"), {"llm_provider_adapter": "claude"})
    assert settings.llm_provider_adapter == "claude"


def test_no_overrides_returns_the_environment_unchanged():
    base = _base()
    assert effective(base, {}) is base


def test_an_override_of_something_unknown_is_ignored_not_applied():
    """A stale row for a setting that no longer exists must not break start-up."""
    settings = effective(_base(), {"setting_that_was_removed": "x"})
    assert settings.llm_provider_adapter == "mock"


# --- what may not ----------------------------------------------------------


def test_a_secret_cannot_be_written_through_the_api():
    """Secrets stay in the environment rather than in a database in plaintext."""
    with pytest.raises(ConfigError, match="secret"):
        validate({"anthropic_api_key": "sk-ant-whatever"})


def test_a_static_setting_cannot_be_changed_at_runtime():
    with pytest.raises(ConfigError, match="cannot be changed"):
        validate({"database_url": "sqlite+aiosqlite:///./elsewhere.db"})


def test_an_unknown_setting_is_rejected():
    with pytest.raises(ConfigError, match="unknown setting"):
        validate({"turbo_mode": True})


def test_an_adapter_value_no_adapter_implements_is_rejected():
    with pytest.raises(ConfigError, match="must be one of"):
        validate({"work_dispatch_adapter": "jenkins"})


# --- coercion --------------------------------------------------------------


@pytest.mark.parametrize(
    "key, raw, expected",
    [
        ("dispatch_timeout_seconds", "900", 900),
        ("reconciler_interval_seconds", "2.5", 2.5),
        ("auto_approve_gates", "true", True),
        ("auto_approve_gates", "off", False),
        ("code_index_max_depth", 5, 5),
    ],
)
def test_values_are_coerced_to_their_declared_type(key, raw, expected):
    assert validate({key: raw})[key] == expected


def test_a_value_of_the_wrong_type_is_rejected_with_the_key_named():
    with pytest.raises(ConfigError, match="dispatch_timeout_seconds"):
        validate({"dispatch_timeout_seconds": "soon"})


def test_an_empty_value_clears_the_override():
    """Clearing restores the environment default rather than storing a blank."""
    assert validate({"github_repo": ""})["github_repo"] is None


# --- what the console is told ----------------------------------------------


def test_secrets_report_presence_and_never_a_value():
    described = {e["key"]: e for e in describe(_base(anthropic_api_key="sk-ant-secret"), {})}
    entry = described["anthropic_api_key"]

    assert entry["configured"] is True
    assert entry["value"] is None
    assert "sk-ant-secret" not in str(described)


def test_a_missing_secret_reports_as_unconfigured():
    described = {e["key"]: e for e in describe(_base(), {})}
    assert described["anthropic_api_key"]["configured"] is False


def test_an_overridden_setting_is_marked_as_such():
    described = {
        e["key"]: e for e in describe(_base(), {"work_dispatch_adapter": "github-actions"})
    }
    assert described["work_dispatch_adapter"]["overridden"] is True
    assert described["work_dispatch_adapter"]["value"] == "github-actions"
    assert described["llm_provider_adapter"]["overridden"] is False


def test_every_spec_names_a_real_setting():
    """A spec for a field that does not exist would render a control that
    silently does nothing."""
    fields = set(Settings.model_fields)
    assert {spec.key for spec in SPECS} <= fields


def test_every_mutable_key_is_actually_settable():
    base = _base()
    for key in MUTABLE_KEYS:
        spec = BY_KEY[key]
        sample = spec.options[0] if spec.options else getattr(base, key)
        if sample is None:
            continue
        assert getattr(effective(base, {key: sample}), key) == sample
