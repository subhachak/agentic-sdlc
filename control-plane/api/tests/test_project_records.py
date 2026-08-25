"""Projects as records, not filter keys.

Engagement settings — which codebase, where changes go, where they ship —
used to live in the global settings table, so two teams could not hold
different answers at the same time. They live on the project now, with the
environment's values as the seed and the fallback.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core import projects
from app.core.config import Settings
from app.graph.projects import ProjectError


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    from app.core.config import get_settings
    from app.core.db import get_engine

    get_settings.cache_clear()
    get_engine.cache_clear()
    from app.main import app

    with TestClient(app) as c:
        yield c
    get_settings.cache_clear()
    get_engine.cache_clear()


# --- the record ------------------------------------------------------------


def test_the_default_project_exists_as_a_record(client):
    """Otherwise every consumer has to remember that "default" means "the one
    with no row", and a fresh install has nothing to show."""
    body = client.get("/api/projects").json()

    assert body["active"] == "default"
    assert [p["id"] for p in body["projects"]] == ["default"]


def test_a_new_project_starts_from_the_environment_rather_than_blank(client):
    """Most defaults are right most of the time, and the two that are not are
    obvious. Thirteen empty fields are not."""
    created = client.post("/api/projects", json={"id": "team-a", "name": "Team A"}).json()
    engagement = created["engagement"]

    assert engagement["qa_export_path"]

    # Derivable fields are deliberately *not* stored. Copying them in froze
    # them as decisions — the console could no longer tell "someone chose
    # this" from "nothing chose this", and asked about four fields that
    # already had answers. They still resolve; they are just not answers the
    # record has to hold.
    assert "target_ref" not in engagement
    assert "github_ref" not in engagement

    # Nor is the export scope. It used to default to the sample app's name,
    # which is a guess about the client's repository layout dressed up as a
    # default — and pointing the platform anywhere else then failed with an
    # error blaming the index.
    assert not engagement.get("qa_export_scope")


def test_a_partial_update_does_not_blank_the_rest(client):
    client.post("/api/projects", json={"id": "team-a"})
    updated = client.put(
        "/api/projects/team-a", json={"engagement": {"target_repo": "acme/widgets"}}
    ).json()

    assert updated["engagement"]["target_repo"] == "acme/widgets"
    # Everything else the record held is still there — a partial update sends
    # only the edited fields and must not blank the rest.
    assert updated["engagement"]["target_environment"]
    # And what the record does not hold still resolves, from derivation.
    assert client.get("/api/config").json()



def test_an_unknown_engagement_key_is_ignored_not_stored(client):
    """The engagement is a defined set. Accepting arbitrary keys would make
    it a second, undocumented settings table."""
    client.post("/api/projects", json={"id": "team-a"})
    updated = client.put(
        "/api/projects/team-a", json={"engagement": {"anthropic_api_key": "sk-nope"}}
    ).json()

    assert "anthropic_api_key" not in updated["engagement"]


def test_a_duplicate_id_is_refused(client):
    client.post("/api/projects", json={"id": "team-a"})
    assert client.post("/api/projects", json={"id": "team-a"}).status_code == 422


def test_an_invalid_id_is_refused(client):
    """A project id ends up inside node identity."""
    assert client.post("/api/projects", json={"id": "Team A"}).status_code == 422


# --- switching -------------------------------------------------------------


def test_activating_a_project_repoints_the_adapters(client):
    """Otherwise an edit takes effect on the next restart, which is the kind
    of quiet lag that has someone indexing the previous client's repository."""
    from app.main import app

    client.post("/api/projects", json={"id": "team-a"})
    client.put("/api/projects/team-a",
               json={"engagement": {"target_repo": "acme/widgets", "target_environment": "prod"}})
    client.post("/api/projects/team-a/activate")

    assert app.state.settings.target_repo == "acme/widgets"
    assert app.state.settings.target_environment == "prod"

    client.post("/api/projects/default/activate")
    assert app.state.settings.target_repo != "acme/widgets"


def test_editing_the_live_project_takes_effect_immediately(client):
    from app.main import app

    client.post("/api/projects", json={"id": "team-a"})
    client.post("/api/projects/team-a/activate")
    client.put("/api/projects/team-a", json={"engagement": {"target_environment": "prod"}})

    assert app.state.settings.target_environment == "prod"


def test_activating_an_unknown_project_is_a_404(client):
    assert client.post("/api/projects/nobody/activate").status_code == 404


def test_a_graph_read_follows_the_active_project(client):
    """An omitted project means the one being worked on, not the literal
    default — defaulting to a constant would reintroduce the cross-project
    read one layer up."""
    client.post("/api/projects", json={"id": "team-a"})
    client.post("/api/projects/team-a/activate")

    assert client.get("/api/graph/modules").json()["project"] == "team-a"


# --- runs ------------------------------------------------------------------


def test_a_run_records_the_project_it_was_started_under(client):
    """A run is a decision about one codebase, and the trail has to still say
    which one after someone switches project."""
    client.post("/api/projects", json={"id": "team-a"})
    client.post("/api/projects/team-a/activate")
    client.post("/api/runs", data={"text": "as a user I want to log in"})

    assert len(client.get("/api/runs").json()) == 1

    client.post("/api/projects/default/activate")
    assert client.get("/api/runs").json() == []
    assert len(client.get("/api/runs?all_projects=true").json()) == 1


# --- lifecycle -------------------------------------------------------------


def test_archiving_hides_without_destroying_the_trail(client):
    client.post("/api/projects", json={"id": "team-a"})
    client.post("/api/projects/team-a/archive")

    assert [p["id"] for p in client.get("/api/projects").json()["projects"]] == ["default"]
    listed = client.get("/api/projects?include_archived=true").json()["projects"]
    assert {p["id"] for p in listed} == {"default", "team-a"}


def test_the_default_project_cannot_be_archived_or_deleted(client):
    assert client.post("/api/projects/default/archive").status_code == 422
    assert client.delete("/api/projects/default").status_code == 422


# --- the overlay -----------------------------------------------------------


def test_a_project_that_answers_nothing_inherits_every_default():
    """A project naming only a repository must not null the rest."""
    settings = Settings(target_ref="main", target_environment="staging")
    record = projects.ProjectRecord(
        id="team-a", name="", description="",
        engagement={"target_repo": "acme/widgets", "target_ref": "", "target_environment": None},
        archived=False,
    )

    applied = projects.applied_to(settings, record)

    assert applied.target_repo == "acme/widgets"
    assert applied.target_ref == "main"
    assert applied.target_environment == "staging"


def test_no_project_leaves_settings_untouched():
    settings = Settings(target_ref="release")
    assert projects.applied_to(settings, None).target_ref == "release"


@pytest.mark.asyncio
async def test_the_default_project_cannot_be_archived_at_the_store_level():
    with pytest.raises(ProjectError):
        await projects.archive("default")
