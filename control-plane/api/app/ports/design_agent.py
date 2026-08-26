"""Port: decide what a change will touch.

The default is this platform's own agent, calling a model in-process. The
reason it is a port is that a client may want their own — the same agent that
writes the code, or a service of their own — and swapping that should be
configuration rather than a fork.

Two shapes have to fit one contract, because they differ in latency by four
orders of magnitude. An in-process call answers in seconds. A client's cloud
agent is dispatched, works for an hour, and answers into a pull request. So
`propose` returns either a proposal or a handle to work in flight, and the
phase parks on the second the same way it parks for CI.

What does not vary is what happens to the answer. The proposal is reviewed
against the context graph — every module and file it names must exist, and
must belong to the modules it claims — before a human is asked to approve it,
whoever produced it. An agent supplied by a client is reviewed exactly as
strictly as the one shipped here, and slightly more suspiciously: it is the
only one that can be changed without anyone here knowing.
"""

from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field


class DesignRequest(BaseModel):
    """Everything an agent needs to propose a bounded change.

    Assembled by the phase rather than fetched by the adapter, so a client's
    agent cannot quietly widen what it looks at — and so the catalogue it
    chooses from is the graph's, not one it built for itself.
    """

    run_id: str
    # Which engagement, and which snapshot of it the catalogue came from.
    # Absent, a proposal could not be replayed: "why did it name that
    # module" is unanswerable once the graph moves, and an approval that
    # cannot say what it approved is not evidence.
    project: str = ""
    graph_commit: str = ""
    requirement: str
    criteria: list[dict[str, Any]] = Field(default_factory=list)
    # Modules that actually exist, with their dependencies and hub files.
    # Naming anything outside this is refused.
    catalogue: list[dict[str, Any]] = Field(default_factory=list)
    context_snippets: list[dict[str, Any]] = Field(default_factory=list)
    max_files: int = 15
    # Populated on a retry: why the previous attempt was refused. An agent
    # that cannot use it may ignore it; the attempt limit applies regardless.
    rejected_reasons: list[str] = Field(default_factory=list)
    # Bumped when this shape changes. A client agent runs in its own
    # process and release cycle, so a field that moved without a version to
    # notice it is a field they misread in silence.
    contract_version: int = 1


class DesignProposal(BaseModel):
    summary: str = ""
    rationale: str = ""
    modules: list[str] = Field(default_factory=list)
    files: list[str] = Field(default_factory=list)
    criteria_addressed: list[str] = Field(default_factory=list)
    out_of_scope: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    # A refusal is a useful answer. A design naming plausible modules the
    # agent has not verified is not.
    blocked: str = ""


class DesignOutcome(BaseModel):
    """Either an answer or a receipt.

    `ready` carries a proposal. `pending` carries what the phase needs to
    park: the provider that started the work and how to ask it later. The
    phase branches on this rather than on which adapter is configured, so
    adding an agent does not add a branch to the phase.
    """

    state: Literal["ready", "pending"]
    proposal: DesignProposal | None = None
    # For the dispatched shape: which WorkDispatch provider to poll, and the
    # inputs it was started with.
    provider: str | None = None
    dispatch_inputs: dict[str, Any] | None = None


class DesignAgent(Protocol):
    contract_version: int

    def capabilities(self) -> dict[str, Any]: ...
    """What this agent can do, read before it is asked.

    An agent that cannot use `rejected_reasons` will ignore a retry's
    feedback and produce the same proposal again, burning the attempt limit
    to no purpose — better to know that than to discover it three refusals
    later. `dispatched` tells the phase whether to expect a receipt at all.

    Keys: dispatched (bool), uses_feedback (bool), max_files (int).
    """

    async def propose(self, request: DesignRequest) -> DesignOutcome: ...

    def read_result(self, payload: dict[str, Any]) -> DesignProposal: ...
    """Turn a finished dispatch's payload into a proposal.

    Separate from `propose` because the two run in different processes: the
    dispatch is resumed by the reconciler after a restart, so whatever the
    provider returned has to be interpretable without the state that started
    it. Synchronous adapters never have this called."""
