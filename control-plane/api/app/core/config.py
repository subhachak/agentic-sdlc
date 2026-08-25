from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# .../control-plane/api/app/core/config.py -> the repository root
REPO_ROOT = Path(__file__).resolve().parents[4]


class Settings(BaseSettings):
    # Two locations, repository root first. The root is the documented one and
    # the only one .env.example describes; a file beside the API still wins,
    # for anyone running it from there directly. Without the root entry, a
    # .env written where the instructions say to write it is silently ignored,
    # because the API's working directory is control-plane/api.
    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env", ".env"), extra="ignore"
    )

    database_url: str = "sqlite+aiosqlite:///./agentic_sdlc.db"

    llm_provider_adapter: Literal["claude", "mock"] = "mock"
    work_dispatch_adapter: Literal["github-actions", "local", "local-pipeline"] = "local"
    code_intelligence_adapter: Literal["github", "local"] = "github"
    source_control_adapter: Literal["github", "local"] = "local"
    # Who writes the change. "inline" is this platform's own agent, refused
    # before its edits reach a branch. "github-copilot" hands the work to the
    # client's cloud agent, which opens its own pull request — containment
    # there is checked after the fact, against what it actually did.
    implementation_agent: Literal["inline", "github-copilot"] = "inline"
    copilot_model: str | None = None
    copilot_custom_agent: str | None = None
    # "repo" grounds the design agent in the indexed repository; "stub" is
    # the fixture placeholder, kept only so tests can run with no source.
    code_design_context_adapter: Literal["repo", "stub"] = "repo"
    claude_model: str = "claude-opus-5"
    anthropic_api_key: str | None = None

    # Which engagement the platform is currently working on. The graph is
    # scoped by it, and the active project's own settings overlay these.
    active_project: str = "default"

    max_node_retries: int = 2
    auto_approve_gates: bool = False

    web_origin: str = "http://localhost:3000"

    # --- remote execution (WorkDispatch) ---
    github_repo: str | None = None
    github_token: str | None = None
    github_workflow_file: str = "agentic-qa.yml"
    github_ref: str = "main"
    dispatch_timeout_seconds: int = 1800

    # --- code intelligence (graph seeding) ---
    # The repository the demo indexes when none is given in the request.
    code_index_repo: str | None = None
    code_index_ref: str = "main"
    # A module is a directory collapsed to this many path segments. Deeper
    # means finer modules; too shallow and a whole service is one node.
    code_index_max_depth: int = 4
    code_index_local_root: str = "."
    # Where the execution plane reads its copy of the graph. It runs in client
    # CI with no route to this database, so the handover is a generated file.
    qa_export_path: str = "execution-plane/qa/code-graph.json"
    # No default. It used to be the sample app's name, so pointing the
    # platform at any other repository failed with a message blaming the
    # index. Empty means "work it out from what was indexed", and the
    # console writes the answer here once someone has chosen.
    qa_export_scope: str = ""

    # --- implementation phase ---
    # The repository the implementation agent proposes changes against, and
    # the working copy the local adapter writes to.
    target_repo: str | None = None
    target_ref: str = "main"
    target_working_copy: str = "."
    target_environment: str = "staging"
    reconciler_interval_seconds: float = 5.0
    local_dispatch_duration_seconds: float = 3.0

    # Which values were filled in from another rather than set. The console
    # shows these as derived instead of as blanks someone forgot, which is
    # the difference between "one repository" and "three fields that must
    # agree with each other".
    derived_keys: frozenset[str] = frozenset()

    @model_validator(mode="after")
    def _derive_on_load(self) -> "Settings":
        return derive(self)



    @property
    def checkpointer_db_path(self) -> str:
        """Separate SQLite file for the LangGraph checkpointer, derived from database_url."""
        if not self.database_url.startswith("sqlite"):
            raise ValueError("Only sqlite database_url is supported in this phase")
        path = self.database_url.split(":///")[-1]
        if path.endswith(".db"):
            return path[: -len(".db")] + "_checkpoints.sqlite"
        return path + "_checkpoints.sqlite"

    @property
    def db_file_path(self) -> str:
        return self.database_url.split(":///")[-1]


def derive(settings: "Settings") -> "Settings":
    """One repository, and the things that follow from it.

    There were three: the one to index, the one changes are proposed against,
    and the one holding the CI workflow — plus a ref each. In almost every
    deployment they are the same value typed three times, and the three that
    are not are the interesting case, not the default.

    So the indexed repository is the engagement's repository, and the rest
    fall back to it. Setting one explicitly still wins, which is what makes
    the uncommon layouts — CI in a separate repository, a fork as the change
    target — possible rather than merely awkward.

    A module-level function rather than only a validator because a project
    record is applied with `model_copy`, which does not re-run validation.
    Without this being callable, choosing a repository for a project would
    leave the derived fields pointing at the previous one.
    """
    derived: set[str] = set()

    def fill(key: str, value: str | None) -> None:
        if not getattr(settings, key, None) and value:
            object.__setattr__(settings, key, value)
            derived.add(key)

    fill("target_repo", settings.code_index_repo)
    fill("github_repo", settings.code_index_repo)

    # A ref is a property of the repository, not a separate decision. Only
    # carried across when the repositories actually match: a base branch from
    # one repository is not a fact about another.
    indexed_ref = settings.code_index_ref
    if indexed_ref and indexed_ref != "main":
        if settings.target_repo == settings.code_index_repo and settings.target_ref == "main":
            object.__setattr__(settings, "target_ref", indexed_ref)
            derived.add("target_ref")
        if settings.github_repo == settings.code_index_repo and settings.github_ref == "main":
            object.__setattr__(settings, "github_ref", indexed_ref)
            derived.add("github_ref")

    object.__setattr__(settings, "derived_keys", frozenset(derived))
    return settings


@lru_cache
def get_settings() -> Settings:
    return Settings()
