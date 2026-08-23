from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite+aiosqlite:///./agentic_sdlc.db"

    llm_provider_adapter: Literal["claude", "mock"] = "mock"
    claude_model: str = "claude-opus-5"
    anthropic_api_key: str | None = None

    max_node_retries: int = 2
    auto_approve_gates: bool = False

    web_origin: str = "http://localhost:3000"

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
