from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite+aiosqlite:///./agentic_sdlc.db"

    llm_provider_adapter: Literal["claude", "mock"] = "mock"
    work_dispatch_adapter: Literal["github-actions", "local"] = "local"
    code_intelligence_adapter: Literal["github", "local"] = "github"
    claude_model: str = "claude-opus-5"
    anthropic_api_key: str | None = None

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
    # A component is a directory collapsed to this many path segments. Deeper
    # means finer components; too shallow and a whole service is one node.
    code_index_max_depth: int = 4
    code_index_local_root: str = "."
    reconciler_interval_seconds: float = 5.0
    local_dispatch_duration_seconds: float = 3.0

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


@lru_cache
def get_settings() -> Settings:
    return Settings()
