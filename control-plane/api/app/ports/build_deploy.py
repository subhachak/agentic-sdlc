"""Port: stubbed downstream Build/Deploy phase target.

Demo adapter: no-op stub that logs a call and returns success.
Future: Jenkins, GitHub Actions, Azure DevOps.
"""

from typing import Any, Protocol

from pydantic import BaseModel


class BuildResult(BaseModel):
    success: bool
    build_id: str
    message: str


class BuildDeploy(Protocol):
    async def trigger_build(self, run_id: str, payload: dict[str, Any]) -> BuildResult: ...
