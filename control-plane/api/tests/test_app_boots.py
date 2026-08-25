"""The application imports and its routes are registered.

Added because a NameError at module scope in a router survived a green suite
of 284 tests: nothing imported `app.main`, so a class referencing another
before it was defined only failed when a person started the server. A test
suite that cannot tell you the application does not start is missing the
cheapest assertion available.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


def test_the_application_imports():
    from app.main import app

    assert app is not None


@pytest.mark.parametrize(
    "path",
    [
        "/api/health",
        "/api/dashboard",
        "/api/config",
        "/api/graph/status",
        "/api/graph/modules",
        "/api/runs",
    ],
)
def test_every_read_endpoint_answers(path):
    from app.main import app

    with TestClient(app) as client:
        assert client.get(path).status_code == 200, path


def test_a_graph_read_is_scoped_to_the_project_asked_for():
    from app.main import app

    with TestClient(app) as client:
        unknown = client.get("/api/graph/modules?project=nobody-has-this").json()

    assert unknown["project"] == "nobody-has-this"
    assert unknown["modules"] == []


def test_an_invalid_project_is_refused_rather_than_silently_scoped():
    from app.main import app

    with TestClient(app) as client:
        response = client.post("/api/graph/seed", json={"repo": "x/y", "project": "Bad Name"})

    assert response.status_code == 422
    assert "invalid project id" in response.json()["detail"]
