import logging
import uuid
from typing import Any

from app.ports.build_deploy import BuildResult

logger = logging.getLogger(__name__)


class NoOpBuildDeploy:
    """Demo-default BuildDeploy adapter: logs the call and returns success.
    Stands in for Jenkins/GitHub Actions/Azure DevOps in a later phase.
    """

    async def trigger_build(self, run_id: str, payload: dict[str, Any]) -> BuildResult:
        build_id = str(uuid.uuid4())
        logger.info("build_deploy stub called: run_id=%s build_id=%s payload=%s", run_id, build_id, payload)
        return BuildResult(success=True, build_id=build_id, message="stub — no-op build/deploy")
