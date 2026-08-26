"""Port: turn an approved change into something running somewhere.

The old contract was `trigger_build(run_id, payload: dict) -> {success,
build_id, message}`. Four things it could not express, each of which a real
deployment platform requires:

  Duration.   It was synchronous. Deployments take minutes to hours, so a
              synchronous contract forces the adapter to either block a
              phase or lie about completion. Every other long-running seam
              here — CI, the coding agent, the design agent — is a dispatch
              with a receipt, and this is the same problem.
  Identity.   `build_id` is the *job*. A release has to name the immutable
              artifact that was deployed — an image digest, a package
              version — or "what is running in staging" is unanswerable and
              the release node describes a job rather than a thing.
  Health.     "The deploy command exited zero" is not "the service works".
              Separating them is what makes a rollback decision possible
              rather than a guess.
  Reversal.   No rollback. A platform that can only go forward is one nobody
              points at production.

`payload: dict[str, Any]` is also how a port stops being a contract: two
adapters can agree to the signature and share nothing.
"""

from __future__ import annotations

from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field


class Artifact(BaseModel):
    """The immutable thing that gets deployed.

    Named separately from the job that produced it because a release is
    about the artifact. Re-deploying the same digest to a second environment
    is one artifact and two deployments, and a model that conflates them
    cannot say what is running where.
    """

    # "container", "package", "bundle", "function" — open, because what
    # counts as an artifact is the client's platform's business.
    kind: str = ""
    # Registry reference, package coordinates, path. Whatever names it.
    reference: str = ""
    # Content identity where the platform offers one: an image digest, a
    # package checksum. This is what makes "the same artifact" checkable
    # rather than asserted.
    digest: str = ""
    build_id: str = ""


class DeployRequest(BaseModel):
    """What to deploy, where, and on whose authority."""

    run_id: str
    environment: str
    # The commit the change was reviewed and approved at. Carried so the
    # deployment can be tied back to the assessment that authorised it —
    # a deployment that cannot name its revision cannot be audited.
    revision: str = ""
    branch: str = ""
    # Which project's engagement this belongs to. Explicit, because a phase
    # that resolves scope from whatever is active when it runs writes a
    # late-arriving record into the wrong client's graph.
    project: str = ""
    # Set when re-deploying something already built, rather than building
    # from the revision.
    artifact: Artifact | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)


class DeployOutcome(BaseModel):
    """Either a result or a receipt.

    The same shape DesignAgent uses, for the same reason: the phase branches
    on the state rather than on which adapter is configured, so adding a
    deployment platform does not add a branch to the phase.
    """

    state: Literal["ready", "pending", "failed"]
    deployment: Deployment | None = None
    # For the dispatched shape: how to ask again later.
    provider: str = ""
    handle: str = ""
    detail: str = ""


class Deployment(BaseModel):
    """What actually happened."""

    deployment_id: str
    environment: str
    artifact: Artifact = Field(default_factory=Artifact)
    revision: str = ""
    # Where a human can go and look. An evidence trail that cannot be opened
    # is a claim.
    url: str = ""
    started_at: str = ""
    finished_at: str = ""
    # Whether the *deployment mechanism* succeeded. Separate from health.
    succeeded: bool = False
    # Whether the thing that was deployed is actually working. None means
    # the adapter cannot tell, which is a legitimate answer and a different
    # one from "healthy".
    healthy: bool | None = None
    detail: str = ""


class BuildDeploy(Protocol):
    async def deploy(self, request: DeployRequest) -> DeployOutcome: ...

    async def check(self, handle: str) -> DeployOutcome: ...
    """Ask a dispatched deployment how it went.

    Separate from `deploy` because the two run in different processes: a
    deployment outlives the request that started it, and the reconciler
    resumes it after a restart with nothing but the handle."""


class RollbackCapable(Protocol):
    """Optional: some platforms can reverse a deployment, some cannot.

    Deliberately not part of BuildDeploy. An adapter for a platform with no
    rollback primitive would have to either lie or raise, and a port that
    forces every implementer to implement something they do not have is how
    a framework acquires stub methods that throw.
    """

    async def rollback(self, deployment_id: str) -> DeployOutcome: ...


DeployOutcome.model_rebuild()
