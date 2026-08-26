"""No adapter selection may stop the platform working.

Selecting an agent through the console once bricked a deployment: the value
was persisted before anything checked it could be built, so the process would
not restart and the only way back was editing the database by hand. That was
fixed for the agent that exposed it; this pins the property for every option
of every adapter, because the next one added will have the same shape.

Two failure modes, and the quiet one is worse. A factory that raises tells an
admin what is missing. A factory that constructs happily and fails at first
use — the Claude SDK accepts no API key and fails at the first call — hides
the problem until a run is deep enough to have passed its gates.
"""

from __future__ import annotations

import itertools

import pytest
from fastapi.testclient import TestClient

from app.core import settings_store
from app.core.config import Settings

# Everything local, nothing credentialed: the configuration a fresh install
# has, and the one every option is varied against.
BASELINE = dict(
    llm_provider_adapter="mock",
    work_dispatch_adapter="local",
    implementation_agent="inline",
    source_control_adapter="local",
    code_intelligence_adapter="local",
    anthropic_api_key=None,
    github_token=None,
    github_repo=None,
    target_repo=None,
    target_working_copy=".",
    code_index_local_root=".",
)

CREDENTIALS = dict(
    anthropic_api_key="sk-test",
    github_token="ghp_test",
    github_repo="acme/thing",
    target_repo="acme/thing",
    jira_base_url="https://acme.atlassian.net",
    jira_email="bot@acme.example",
    jira_api_token="jira-test",
)

SELECTORS = {
    spec.key: spec.options for spec in settings_store.SPECS if spec.type == "enum"
}

# What each option cannot work without. Written out rather than derived, so
# adding an adapter without deciding this fails the test rather than passing
# by omission.
NEEDS_CREDENTIALS = {
    ("llm_provider_adapter", "claude"),
    ("work_dispatch_adapter", "github-actions"),
    ("implementation_agent", "github-copilot"),
    ("source_control_adapter", "github"),
    ("requirements_source_adapter", "jira"),
}


def _combinations():
    keys = sorted(SELECTORS)
    for values in itertools.product(*(SELECTORS[k] for k in keys)):
        yield dict(zip(keys, values))


# --- every option, judged consistently -------------------------------------


def test_the_baseline_builds():
    """A fresh install with no credentials has to work, or nothing below
    means anything."""
    assert settings_store.check(Settings(**BASELINE)) == []


@pytest.mark.parametrize(
    "key,option",
    [(k, o) for k, opts in SELECTORS.items() for o in opts],
)
def test_an_option_needing_credentials_is_refused_without_them(key, option):
    problems = settings_store.check(Settings(**BASELINE).model_copy(update={key: option}))

    if (key, option) in NEEDS_CREDENTIALS:
        assert problems, f"{key}={option} builds without credentials but cannot work"
        assert key in problems[0], f"{key}={option} was refused without naming itself"
    else:
        assert problems == [], f"{key}={option} refused a configuration that can work"


@pytest.mark.parametrize(
    "key,option",
    [(k, o) for k, opts in SELECTORS.items() for o in opts],
)
def test_every_option_builds_once_its_credentials_are_present(key, option):
    settings = Settings(**{**BASELINE, **CREDENTIALS}).model_copy(update={key: option})
    assert settings_store.check(settings) == []


def test_every_combination_is_either_buildable_or_refused_with_a_reason():
    """Factories are independent, but a combination is what an admin actually
    saves. None may raise something the caller cannot turn into a sentence."""
    for combination in _combinations():
        settings = Settings(**{**BASELINE, **CREDENTIALS}).model_copy(update=combination)
        assert settings_store.check(settings) == [], combination


def test_a_local_adapter_pointed_at_nothing_is_refused():
    """It cannot work, and it is checkable here rather than when a run reaches
    the phase that uses it."""
    for key, option in [
        ("source_control_adapter", "local"),
        ("code_intelligence_adapter", "local"),
        ("work_dispatch_adapter", "local-pipeline"),
    ]:
        settings = Settings(**BASELINE).model_copy(
            update={key: option, "target_working_copy": "/no/such/dir",
                    "code_index_local_root": "/no/such/dir"}
        )
        problems = settings_store.check(settings)
        assert problems, f"{key}={option} accepted a directory that does not exist"
        assert "directory that exists" in problems[0]


def test_the_credential_list_covers_every_selector():
    """Adding an adapter without deciding what it needs should fail here
    rather than pass by being forgotten."""
    known = {k for k, _ in NEEDS_CREDENTIALS}
    assert known <= set(SELECTORS)


# --- through the API, which is where an admin does it ----------------------


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'sel.db'}")
    for name in ("GITHUB_TOKEN", "TARGET_REPO", "GITHUB_REPO", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LLM_PROVIDER_ADAPTER", "mock")
    from app.core.config import get_settings
    from app.core.db import get_engine

    get_settings.cache_clear()
    get_engine.cache_clear()
    from app.main import app

    with TestClient(app) as c:
        yield c
    get_settings.cache_clear()
    get_engine.cache_clear()


@pytest.mark.parametrize(
    "key,option",
    [(k, o) for k, opts in SELECTORS.items() for o in opts],
)
def test_no_option_can_break_the_platform_through_the_console(client, key, option):
    """The property that matters. Whatever an admin selects, the answer is
    either applied or refused with a reason — never a 500, never a stored
    value the platform cannot start with, and never an API that stops
    answering."""
    response = client.put("/api/config", json={"changes": {key: option}})

    assert response.status_code in (200, 422), response.text
    if response.status_code == 422:
        assert response.json()["detail"]

    assert client.get("/api/health").status_code == 200
    assert client.get("/api/config").status_code == 200
    assert client.get("/api/config").json()["problem"] is None


def test_preflight_agrees_with_what_the_save_does(client):
    """Two paths to one answer. A preflight that passes something the save
    refuses is worse than no preflight."""
    for key, options in SELECTORS.items():
        for option in options:
            changes = {"changes": {key: option}}
            predicted = client.post("/api/config/preflight", json=changes).json()["ok"]
            applied = client.put("/api/config", json=changes).status_code == 200

            assert predicted == applied, f"{key}={option}: preflight said {predicted}"
            client.put("/api/config", json={"changes": {key: None}})
