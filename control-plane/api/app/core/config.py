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
    # Empty means "follow the index source". Where the code is read from and
    # where changes are proposed are the same question in every ordinary
    # setup, and they were two independent settings with opposite defaults —
    # so indexing from GitHub while proposing changes into an unrelated local
    # checkout was what you got by doing nothing.
    source_control_adapter: Literal["github", "local", ""] = ""
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
    # Ports whose implementation used to be chosen by whichever concrete
    # class build_adapters happened to import. A client bringing Jira for
    # requirements or ServiceNow for test cases had to edit that function,
    # which is the fork the ports exist to prevent.
    requirements_source_adapter: Literal["csv"] = "csv"
    test_management_adapter: Literal["json-file"] = "json-file"
    build_deploy_adapter: Literal["noop"] = "noop"
    audit_sink_adapter: Literal["sqlite"] = "sqlite"
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


def canonical_repo(value: str | None) -> str | None:
    """A repository name reduced to one form.

    `https://github.com/acme/widgets` and `acme/widgets` are one repository
    written two ways. Comparing them raw makes a value identical to the
    derived one look like a deliberate override.
    """
    if not value:
        return None
    text = value.strip().rstrip("/")
    for prefix in ("https://github.com/", "http://github.com/", "git@github.com:"):
        if text.startswith(prefix):
            text = text[len(prefix):]
    return text.removesuffix(".git").lower()


def undone(settings: "Settings") -> dict:
    """This settings object as a dict, with derivation undone.

    Anything that rebuilds a Settings from an existing one has to strip what
    derivation filled in first. Dumping a derived object and re-validating
    makes every derived value look explicitly chosen, so it is never
    re-derived when the thing it was derived *from* changes — which is how a
    field went on naming the previous repository, and how the console
    reported a derived value as one someone had set.
    """
    data = settings.model_dump()
    for key in settings.derived_keys:
        if key in Settings.model_fields:
            # The field's own default, not None: `target_ref` defaults to
            # "main", and blanking it nulls a default derivation cannot
            # refill when no repository is named.
            data[key] = Settings.model_fields[key].default
    data.pop("derived_keys", None)
    return data


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

    # Where changes are proposed follows where code is read from. Grounding
    # asks source control for the files the graph names, so the two
    # answering different repositories means the design agent reads nothing.
    if not settings.source_control_adapter:
        object.__setattr__(settings, "source_control_adapter", settings.code_intelligence_adapter)
        derived.add("source_control_adapter")

    fill("target_repo", settings.code_index_repo)
    fill("github_repo", settings.code_index_repo)

    # A value that already equals what derivation would have produced is not
    # a separate decision, however it got there — an environment variable
    # repeating the repository is still the repository. Marked derived so the
    # console shows it as worked out rather than asking about it again, which
    # is what made one repository look like three different questions.
    indexed_repo = canonical_repo(settings.code_index_repo)
    for key in ("target_repo", "github_repo"):
        # Both sides must name something. Nothing is derived from nothing,
        # and two absent values are not a match.
        if key in derived or not indexed_repo:
            continue
        if canonical_repo(getattr(settings, key, None)) == indexed_repo:
            derived.add(key)

    # A ref is a property of the repository, not a separate decision. Only
    # carried across when the repositories actually match: a base branch from
    # one repository is not a fact about another.
    indexed_ref = settings.code_index_ref
    # Same rule for refs: a base branch equal to the indexed ref is not an
    # independent answer, and the common case is that all three say "main".
    for key, repo_key in (("target_ref", "target_repo"), ("github_ref", "github_repo")):
        if key in derived:
            continue
        same_repo = bool(indexed_repo) and canonical_repo(
            getattr(settings, repo_key, None)
        ) == indexed_repo
        if same_repo and getattr(settings, key, None) == indexed_ref:
            derived.add(key)

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
