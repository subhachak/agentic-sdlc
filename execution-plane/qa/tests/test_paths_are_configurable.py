"""The QA plane has to be able to point at somebody else's application.

Only APP_ROOT and CODE_GRAPH_FILE were overridable, so the pipeline could be
aimed at another repository's *code* while still reading demo-app's
acceptance criteria and demo-app's regression scripts — testing one
application against another's expectations, which is worse than refusing to
run.

A client's regression suite is their own and lives in their repository; a
client's criteria come from their tracker. Neither belongs to this package.
"""

from __future__ import annotations

import importlib

import pytest

OVERRIDES = {
    "QA_APP_ROOT": "APP_ROOT",
    "QA_SCRIPT_LIBRARY": "LIBRARY_DIR",
    "QA_SCRIPT_MANIFEST": "MANIFEST_FILE",
    "QA_FEATURES": "FEATURES_FILE",
    "QA_GENERATED_DIR": "GENERATED_DIR",
    "QA_DATA_STORE": "DATA_STORE",
    "QA_CODE_GRAPH": "CODE_GRAPH_FILE",
}


@pytest.mark.parametrize("env,attr", sorted(OVERRIDES.items()))
def test_every_path_can_point_somewhere_else(env, attr, tmp_path, monkeypatch):
    target = tmp_path / "elsewhere"
    monkeypatch.setenv(env, str(target))
    from orchestrator import paths

    importlib.reload(paths)
    assert getattr(paths, attr) == target, (
        f"{attr} ignored {env}, so the pipeline cannot be pointed at another app"
    )


def test_the_defaults_still_describe_the_bundled_demo(monkeypatch):
    """Overridable, not unset. A deployment that configures nothing still
    runs against demo-app, which is what makes the sample work out of the box.
    """
    for env in OVERRIDES:
        monkeypatch.delenv(env, raising=False)
    from orchestrator import paths

    importlib.reload(paths)
    assert paths.APP_ROOT.name == "demo-app"
    assert paths.FEATURES_FILE.name == "features.yaml"
    assert paths.LIBRARY_DIR.name == "test-scripts"


def test_pointing_at_fronei_resolves_every_path(tmp_path, monkeypatch):
    """The configuration the demo will actually use."""
    app = tmp_path / "fronei" / "apps" / "web"
    app.mkdir(parents=True)
    monkeypatch.setenv("QA_APP_ROOT", str(app))
    monkeypatch.setenv("QA_SCRIPT_LIBRARY", str(app / "e2e"))
    monkeypatch.setenv("QA_FEATURES", str(tmp_path / "fronei-features.yaml"))
    from orchestrator import paths

    importlib.reload(paths)
    assert paths.APP_ROOT == app
    assert paths.LIBRARY_DIR == app / "e2e"
    # Derived paths follow the app they were told about, rather than
    # silently staying beside the bundled demo.
    assert paths.GENERATED_DIR.is_relative_to(app)
    assert paths.EVIDENCE_DIR.is_relative_to(app.parent)


@pytest.fixture(autouse=True)
def _restore_defaults():
    """Reload with a clean environment afterwards, or a later test inherits
    a paths module still pointed at a temporary directory."""
    yield
    from orchestrator import paths

    importlib.reload(paths)
