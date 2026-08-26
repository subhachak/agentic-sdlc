"""Port: write the change the design named.

This was the one agent-substitution point with no port. A client's coding
agent was selected by a setting and bound directly to WorkDispatch, so
"implement this" travelled as `{"prompt": str, "base_ref": str, "repo": str}`
— an untyped dict through a port whose vocabulary is CI jobs.

Three things that cost:

  The brief was prose in a dict. What the agent may touch, what it must not,
  and what its output has to contain were conventions carried in a string.
  A client implementing WorkDispatch had no way to learn that the payload it
  returns must contain `head_ref`, or that the scope constraints in the
  prompt are the ones containment will be checked against afterwards.

  The vocabulary was wrong. `trigger(run_id, phase, correlation_id, inputs)`
  is a CI job. A coding agent has agent concerns — allowed files, a base
  ref, a budget, what to do when it cannot comply — and every one of them
  was smuggled through `inputs`.

  `check_access` was undeclared. It existed on the GitHub Copilot adapter
  and the console found it with `getattr`. That is the same shape as
  RepositoryCatalogue and RollbackCapable, but as an unwritten convention
  rather than a declared capability.

Deliberately *not* a second WorkDispatch. The dispatch mechanism — reserve a
row, trigger, park, reconcile, resolve — is genuinely shared with CI and
stays in one place; a duplicate would be worse than the untyped dict. This
is a typed façade over it, exactly as DesignAgent is, so the two agent seams
are modelled the same way instead of two different ways.

What does not vary is what happens to the answer. A change is reviewed
against the graph — every file it touched must be one the design named —
whoever wrote it. A client's agent is reviewed exactly as strictly as the
one shipped here, and slightly more suspiciously: it is the only one that
can be changed without anyone here knowing.
"""

from __future__ import annotations

from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field


class ImplementationRequest(BaseModel):
    """Everything an agent needs to write a bounded change.

    Assembled by the phase rather than fetched by the adapter, so a client's
    agent cannot quietly widen what it may touch — and so the constraint it
    is given is the same one containment is checked against afterwards.
    """

    run_id: str
    project: str = ""
    requirement: str = ""
    # The approved design, and the brief built from it. `brief` stays prose
    # because that is what an agent reads; the structured fields beside it
    # are what the platform enforces, and they are not derived from parsing
    # the prose back out again.
    brief: str = ""
    design_summary: str = ""
    # The only files this change may touch. Not advice — a change that
    # touches anything else is refused, whoever produced it.
    allowed_files: list[str] = Field(default_factory=list)
    # Their current contents, read by the phase. Handed over rather than
    # fetched by the adapter, so a client's agent reads what the platform
    # decided it may read — an agent that fetched its own would be choosing
    # its own context and the constraint would be advisory.
    #
    # Empty for a dispatched agent, which has the repository itself.
    sources: dict[str, str] = Field(default_factory=dict)
    allowed_modules: list[str] = Field(default_factory=list)
    criteria: list[dict[str, Any]] = Field(default_factory=list)
    # Where the change is proposed, and from what.
    repo: str = ""
    base_ref: str = ""
    branch: str = ""
    # Bumped when this shape changes. A client agent runs in its own process
    # and release cycle; a field that moved with no version to notice it is
    # a field they misread in silence.
    contract_version: int = 1


class FileChange(BaseModel):
    path: str
    content: str


class ImplementationResult(BaseModel):
    """What the agent actually did.

    `head_ref` is what makes the work findable — the platform reads the
    branch to see what changed rather than trusting a list of files the
    agent reports. A refusal is a useful answer and carries `blocked`.
    """

    summary: str = ""
    head_ref: str = ""
    base_ref: str = ""
    pull_request_id: str = ""
    # The commits the change sits between, and where to look at it. Part of
    # what the agent did, not incidental transport detail: without them the
    # change cannot be diffed and the review has nothing to read.
    head_sha: str = ""
    base_sha: str = ""
    url: str = ""
    # Present when the agent writes in-process. Empty for a dispatched agent,
    # whose work is read from the branch it pushed.
    edits: list[FileChange] = Field(default_factory=list)
    files: list[str] = Field(default_factory=list)
    blocked: str = ""


class ImplementationOutcome(BaseModel):
    """Either an answer or a receipt.

    The same shape DesignAgent and BuildDeploy use, so the phase branches on
    the state rather than on which adapter is configured — adding an agent
    does not add an arm to the phase.
    """

    state: Literal["ready", "pending", "failed"]
    result: ImplementationResult | None = None
    # For the dispatched shape: which WorkDispatch provider was started, and
    # the inputs it was started with. The phase reserves the row and the
    # reconciler resumes it; this port never resumes the graph itself.
    provider: str = ""
    dispatch_inputs: dict[str, Any] = Field(default_factory=dict)
    detail: str = ""


class ImplementationAgent(Protocol):
    contract_version: int

    def capabilities(self) -> dict[str, Any]: ...
    """What this agent can do, read before it is asked.

    Keys: dispatched (bool), opens_pull_request (bool), honours_allowed_files
    (bool), max_files (int).

    `honours_allowed_files` is the interesting one. An agent that does not
    is not refused — it is reviewed the same way afterwards — but the phase
    can say so up front rather than discovering it as a containment failure
    on every run.
    """

    async def implement(self, request: ImplementationRequest) -> ImplementationOutcome: ...

    def read_result(self, payload: dict[str, Any]) -> ImplementationResult: ...
    """Turn a finished dispatch's payload into a result.

    Separate from `implement` because the two run in different processes: a
    two-hour agent run outlives the request that started it and is resumed
    by the reconciler after a restart, so whatever the provider returned has
    to be interpretable without the state that started it."""


class AccessCheckable(Protocol):
    """Optional: verify the agent is reachable before a run depends on it.

    Optional because an in-process agent has nothing to reach, and an
    adapter that had to implement a connection test for a connection it does
    not make would have to return a fiction.
    """

    async def check_access(self) -> dict[str, Any]: ...
