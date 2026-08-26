"""Records what would have been deployed, and deploys nothing.

The default, and honest about it: `succeeded` is true because the recording
succeeded, and `healthy` is None because nothing was deployed for anything
to be healthy about. A stub that claimed health would make the release gate
pass on evidence it invented.
"""

from __future__ import annotations

import uuid

from app.ports.build_deploy import (
    Artifact,
    DeployOutcome,
    Deployment,
    DeployRequest,
)
from app.ports.requirements_source import now


class NoOpBuildDeploy:
    async def deploy(self, request: DeployRequest) -> DeployOutcome:
        stamp = now()
        return DeployOutcome(
            state="ready",
            deployment=Deployment(
                deployment_id=f"noop-{uuid.uuid4().hex[:8]}",
                environment=request.environment,
                artifact=request.artifact
                or Artifact(kind="none", reference=request.branch, build_id=""),
                revision=request.revision,
                started_at=stamp,
                finished_at=stamp,
                succeeded=True,
                # Not False, which would mean "checked and unhealthy".
                healthy=None,
                detail="recorded only; no deployment platform is configured",
            ),
        )

    async def check(self, handle: str) -> DeployOutcome:
        # Nothing is ever pending here, so being asked is a caller error
        # rather than a state to report.
        return DeployOutcome(
            state="failed", detail=f"nothing was dispatched, so {handle!r} is unknown"
        )
