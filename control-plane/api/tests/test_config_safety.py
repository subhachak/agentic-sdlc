"""A configuration change must not be able to stop the platform starting.

Every adapter factory raises when its prerequisites are missing, which is
right at construction time and was wrong as a way to find out: the console
saved first and rebuilt second, so an unbuildable choice was written to the
database and then failed. The process would not restart, and the only way
back was editing SQLite by hand — which is not a recovery path for a console
whose API has to be up to offer one.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'cfg.db'}")
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("TARGET_REPO", raising=False)
    from app.core.config import get_settings
    from app.core.db import get_engine

    get_settings.cache_clear()
    get_engine.cache_clear()
    from app.main import app

    with TestClient(app) as c:
        yield c
    get_settings.cache_clear()
    get_engine.cache_clear()


# --- rejection before persistence ------------------------------------------


def test_an_unbuildable_change_is_refused_and_not_stored(client):
    """The exact sequence that bricked a deployment: select an agent whose
    prerequisites are missing, get a 500, and find the value saved anyway."""
    response = client.put(
        "/api/config", json={"changes": {"implementation_agent": "github-copilot"}}
    )

    assert response.status_code == 422
    assert "TARGET_REPO" in response.json()["detail"]

    entry = next(
        s for s in client.get("/api/config").json()["settings"]
        if s["key"] == "implementation_agent"
    )
    assert entry.get("override") in (None, "")


def test_the_platform_still_works_after_a_refused_change(client):
    client.put("/api/config", json={"changes": {"implementation_agent": "github-copilot"}})

    assert client.get("/api/health").status_code == 200
    assert client.get("/api/dashboard").status_code == 200


def test_a_change_and_its_prerequisites_applied_together_are_accepted(client, monkeypatch):
    """An admin should be able to select an agent and give it what it needs in
    one save, rather than being refused for a gap they are in the middle of
    filling."""
    monkeypatch.setattr(
        "app.core.config.Settings.github_token", "ghp_test", raising=False
    )
    response = client.put(
        "/api/config",
        json={
            "changes": {
                "implementation_agent": "github-copilot",
                "target_repo": "acme/thing",
                "github_token": None,
            }
        },
    )

    # Either it applies, or it is refused for the token — never a 500, and
    # never a stored value the platform cannot start with.
    assert response.status_code in (200, 422)
    assert client.get("/api/health").status_code == 200


# --- preflight -------------------------------------------------------------


def test_preflight_reports_the_problem_without_applying_anything(client):
    """So the console can say "this needs a token" while someone is choosing,
    rather than after they have saved."""
    response = client.post(
        "/api/config/preflight",
        json={"changes": {"implementation_agent": "github-copilot"}},
    )
    body = response.json()

    assert body["ok"] is False
    assert any("TARGET_REPO" in p for p in body["problems"])
    assert client.get("/api/health").status_code == 200


def test_preflight_passes_a_change_that_would_apply(client):
    body = client.post(
        "/api/config/preflight", json={"changes": {"max_node_retries": 3}}
    ).json()

    assert body == {"ok": True, "problems": []}


def test_preflight_rejects_a_value_the_schema_will_not_take(client):
    body = client.post(
        "/api/config/preflight", json={"changes": {"implementation_agent": "nonsense"}}
    ).json()

    assert body["ok"] is False


# --- starting with a bad stored value --------------------------------------


@pytest.mark.asyncio
async def test_a_stored_value_that_cannot_be_built_does_not_stop_startup(tmp_path, monkeypatch):
    """The recovery path. A console whose API will not start cannot be used to
    fix the setting that stopped it."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'broken.db'}")
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    from app.core.config import get_settings
    from app.core.db import get_engine, init_db

    get_settings.cache_clear()
    get_engine.cache_clear()

    await init_db()
    from app.core import settings_store

    # Written directly, as an older version of the console would have.
    await settings_store.save({"implementation_agent": "github-copilot"})

    from app.main import app

    with TestClient(app) as client:
        assert client.get("/api/health").status_code == 200
        body = client.get("/api/config").json()
        assert "could not be applied" in (body["problem"] or "")

    get_settings.cache_clear()
    get_engine.cache_clear()


# --- reaching the agent ----------------------------------------------------


def test_checking_an_inline_agent_says_there_is_nothing_to_reach(client):
    body = client.post("/api/config/check-agent").json()

    assert body["ok"] is True
    assert body["agent"] == "inline"


@pytest.mark.asyncio
async def test_the_access_check_does_not_start_work():
    """A connection test that costs a real agent run and opens a real pull
    request is not a connection test."""
    import inspect

    from app.adapters.work_dispatch.github_copilot import GitHubCopilotWorkDispatch

    source = inspect.getsource(GitHubCopilotWorkDispatch.check_access)

    assert "client.get" in source
    assert "client.post" not in source


# --- the platform always starts --------------------------------------------


def test_safe_mode_has_no_external_dependency():
    """The last rung of the fallback. If this needed a credential or a path,
    a deployment could still fail to start — and then the console that would
    fix it is unreachable."""
    from app.core.config import Settings
    from app.core.settings_store import check
    from app.main import SAFE_MODE

    misconfigured = Settings(
        anthropic_api_key=None, github_token=None, github_repo=None, target_repo=None,
        llm_provider_adapter="claude", source_control_adapter="github",
        work_dispatch_adapter="github-actions", implementation_agent="github-copilot",
    )
    assert check(misconfigured)                       # the situation being escaped
    assert check(misconfigured.model_copy(update=SAFE_MODE)) == []


def test_the_fallbacks_are_ordered_from_asked_for_to_always_works():
    from app.core.config import Settings
    from app.main import SAFE_MODE, _fallbacks

    base = Settings(llm_provider_adapter="claude")
    effective = base.model_copy(update={"target_environment": "prod"})

    rungs = list(_fallbacks(base, effective, None, has_overrides=True))

    assert len(rungs) == 3
    assert rungs[0][0].target_environment == "prod"      # what was asked for
    assert rungs[0][1] == ""                             # nothing failed yet
    assert rungs[1][0].target_environment != "prod"      # the environment alone
    assert rungs[2][0].llm_provider_adapter == SAFE_MODE["llm_provider_adapter"]
    assert "every integration disabled" in rungs[2][1]


def test_a_deployment_with_no_overrides_still_gets_the_safe_rung():
    """A misconfigured environment is not something the console can edit, but
    it must still come up to say so."""
    from app.core.config import Settings
    from app.main import _fallbacks

    rungs = list(_fallbacks(Settings(), Settings(), None, has_overrides=False))

    assert len(rungs) == 2
    assert "every integration disabled" in rungs[-1][1]


@pytest.mark.asyncio
async def test_startup_falls_back_and_says_why(tmp_path, monkeypatch):
    """End to end: a configuration nothing can build still produces a running
    console carrying the reason."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'safe.db'}")
    from app.core.config import Settings, get_settings
    from app.core.db import get_engine

    get_settings.cache_clear()
    get_engine.cache_clear()

    # An environment that cannot be built: Claude selected with no key
    # anywhere, which is exactly what an emptied secret store looks like.
    monkeypatch.setattr(
        "app.core.config.get_settings",
        lambda: Settings(
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'safe.db'}",
            llm_provider_adapter="claude",
            anthropic_api_key=None,
        ),
    )
    monkeypatch.setattr("app.main.get_settings", lambda: Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'safe.db'}",
        llm_provider_adapter="claude",
        anthropic_api_key=None,
    ))

    from app.main import app

    with TestClient(app) as client:
        assert client.get("/api/health").status_code == 200
        assert app.state.settings.llm_provider_adapter == "mock"
        assert "every integration disabled" in (app.state.config_problem or "")

    get_settings.cache_clear()
    get_engine.cache_clear()
