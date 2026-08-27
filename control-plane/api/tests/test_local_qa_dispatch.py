"""Running the execution plane against somebody else's repository.

The local QA adapter derived the orchestrator's location from the repository
under test — `<target>/execution-plane/qa`. That held for exactly one case,
the platform testing its own sample app, and looked like configuration the
whole time. Pointed at a client checkout it failed as a missing interpreter,
which blames the wrong thing.

Two roots: the execution plane belongs to this platform, the application
belongs to the client, and neither is derivable from the other.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from app.adapters.work_dispatch.local_pipeline import (
    _PLATFORM_QA_ROOT,
    LocalPipelineWorkDispatch,
)


def _repo(tmp_path: Path) -> Path:
    def git(*args: str):
        subprocess.run(["git", *args], cwd=tmp_path, capture_output=True, check=True)

    git("init", "-b", "main")
    git("config", "user.email", "t@example.com")
    git("config", "user.name", "T")
    (tmp_path / "apps" / "web").mkdir(parents=True)
    (tmp_path / "apps" / "web" / "package.json").write_text("{}")
    git("add", ".")
    git("commit", "-m", "base")
    return tmp_path


def test_the_execution_plane_is_the_platforms_not_the_clients(tmp_path):
    """A client repository has no execution-plane directory, and requiring
    one would mean shipping the orchestrator into every repo it tests."""
    client = _repo(tmp_path)
    assert not (client / "execution-plane").exists()

    dispatch = LocalPipelineWorkDispatch(client, app_subdir="apps/web")
    assert dispatch._qa_dir == _PLATFORM_QA_ROOT
    assert (dispatch._qa_dir / "orchestrator").is_dir()


def test_the_app_under_test_is_not_assumed_to_be_the_sample(tmp_path):
    dispatch = LocalPipelineWorkDispatch(_repo(tmp_path), app_subdir="apps/web")
    assert dispatch._app_subdir == "apps/web"


def test_an_app_that_starts_itself_is_not_built_twice(tmp_path):
    """A Playwright config with a `webServer` block boots the application.
    Building ahead of it is minutes spent producing something nothing runs,
    so an empty build command is a real configuration rather than a missing
    one — and must not be quietly replaced by a default."""
    dispatch = LocalPipelineWorkDispatch(
        _repo(tmp_path), app_subdir="apps/web", build_command=""
    )
    assert dispatch._build_command == ""


@pytest.mark.asyncio
async def test_the_assessment_travels_as_a_file_not_an_argument(tmp_path, monkeypatch):
    """An assessment carries its explanation — the hops, the blind spots, the
    policy under which it was made. A command line is the wrong place for
    that, and truncating it to a module list would hand the provider a
    verdict it cannot argue with."""
    client = _repo(tmp_path)
    dispatch = LocalPipelineWorkDispatch(client, app_subdir="apps/web", build_command="")

    captured: dict = {}

    class _Process:
        pid = 1234

    def fake_popen(command, **kwargs):
        captured["command"] = command
        captured["env"] = kwargs.get("env") or {}
        return _Process()

    monkeypatch.setattr(dispatch, "_checkout", lambda branch, into: into / "apps/web")
    monkeypatch.setattr(type(dispatch), "_python", property(lambda self: Path(__file__)))
    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    impact = {"engine_version": "1.0.0", "affected": ["apps/web/lib/a.ts"], "paths": []}
    await dispatch.trigger(
        "run-1", "qa", "corr-1", {"branch": "main", "impact": impact, "repo": "acme/web"}
    )

    command = captured["command"]
    assert "--impact" in command
    written = json.loads(Path(command[command.index("--impact") + 1]).read_text())
    assert written["affected"] == ["apps/web/lib/a.ts"]
    # And the explanation survives the trip rather than being flattened.
    assert "engine_version" in written


@pytest.mark.asyncio
async def test_without_an_assessment_no_file_is_invented(tmp_path, monkeypatch):
    """The run then scopes to the edit alone and warns. Writing an empty
    assessment instead would look like one that found nothing."""
    dispatch = LocalPipelineWorkDispatch(_repo(tmp_path), app_subdir="apps/web")

    class _Process:
        pid = 1

    captured: dict = {}
    monkeypatch.setattr(dispatch, "_checkout", lambda branch, into: into / "apps/web")
    monkeypatch.setattr(type(dispatch), "_python", property(lambda self: Path(__file__)))
    monkeypatch.setattr(
        subprocess, "Popen",
        lambda command, **kw: (captured.setdefault("command", command), _Process())[1],
    )

    await dispatch.trigger("run-1", "qa", "corr-2", {"branch": "main"})
    assert "--impact" not in captured["command"]


@pytest.mark.asyncio
async def test_the_pipeline_reads_the_branch_under_test_not_the_working_copy(
    tmp_path, monkeypatch
):
    """QA_SCRIPT_MANIFEST and the rest are resolved against the checkout, so
    a run scopes one revision by that revision's files. Resolving them
    against the working copy would score a branch's change with whatever
    manifest happens to be on disk."""
    client = _repo(tmp_path)
    dispatch = LocalPipelineWorkDispatch(
        client,
        app_subdir="apps/web",
        build_command="",
        qa_env={"QA_SCRIPT_MANIFEST": "e2e/manifest.json"},
    )

    class _Process:
        pid = 2

    captured: dict = {}
    checkout = tmp_path / "wt" / "apps/web"
    monkeypatch.setattr(dispatch, "_checkout", lambda branch, into: checkout)
    monkeypatch.setattr(type(dispatch), "_python", property(lambda self: Path(__file__)))
    monkeypatch.setattr(
        subprocess, "Popen",
        lambda command, **kw: (captured.update(env=kw.get("env") or {}), _Process())[1],
    )

    await dispatch.trigger("run-1", "qa", "corr-3", {"branch": "feature"})

    assert captured["env"]["QA_SCRIPT_MANIFEST"] == str(checkout / "e2e/manifest.json")
    assert captured["env"]["QA_APP_ROOT"] == str(checkout)
