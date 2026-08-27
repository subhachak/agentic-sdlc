"""Port: prove the change works, and produce evidence for it.

The last phase with no port. QA called WorkDispatch directly with an untyped
dict — `{base_sha, head_sha, changed_paths, branch}` — a shape defined
nowhere but the phase that wrote it. Design and implementation both got a
typed façade; QA did not, and it is the phase with the largest contract of
the three.

What a QA provider owes the platform is *evidence*, not a pass mark. How it
arrives at that evidence is entirely its own business: which scripts to
reuse, which to write, how to seed and tear down data, what runner to use.
A client with a mature QA estate already answers all of those, and a port
that dictated them would be asking them to throw that away.

So the request says what changed, how far it reaches and what must be
proven; the result says what was actually observed and what it settled for.
Everything between is the provider's.

Reach is handed down rather than asked for. The platform holds the
dependency graph and the canonical impact engine; a client's QA system
usually holds neither, and where it does, a second traversal is a second
answer. What stays here is the reconciliation — obligation out, accounting
back, deterministic code comparing them.

Two shapes, as with implementation:

  local       the framework's own QA pipeline, inside its boundary. Script
              selection, generation, data lifecycle and execution are the
              execution plane's ports — TestAuthor, TestDataProvider,
              TestRunner — and nothing leaves.
  dispatched  the client's QA automation. The platform hands over the
              contract and waits, through the same dispatch seam CI and the
              coding agent use.

What does not vary is what the answer has to contain. A provider reports
which criteria were exercised and by what, and the platform writes those as
graph edges attributed to the run that asserted them. A provider that
returns "passed" and nothing else has reported an opinion, and the release
gate treats it as one.
"""

from __future__ import annotations

from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field


class QARequest(BaseModel):
    """What changed, and what has to be proven about it.

    Assembled by the phase. A provider that fetched its own scope could
    quietly test something other than the change that was approved.
    """

    run_id: str
    project: str = ""
    # The revision pair. Both required in practice: a QA run that cannot say
    # what it is diffing tests whatever it happens to check out, which reads
    # exactly like a pass for a change it never saw.
    base_sha: str = ""
    head_sha: str = ""
    branch: str = ""
    repo: str = ""
    # What the implementation actually touched.
    changed_paths: list[str] = Field(default_factory=list)
    # How far that reaches, from the one engine that decides it.
    #
    # This used to be the provider's job to work out, on the reasoning that
    # reach is a property of the codebase being tested. That was wrong twice.
    # A client's QA system generally has no dependency graph to widen with,
    # so it would have to guess or skip; and where it does have one, it
    # answers a question the platform already answered differently — which
    # is how the design gate and the QA plane came to run on two blast radii
    # in the same run. Impact is computed once, in app/core/impact.py, and
    # handed down.
    #
    # The full Assessment, not a bare list: `paths` explains why each entity
    # is in scope, `blind_spots` and `unmapped` say what the graph could not
    # see, and `policy` plus `engine_version` say under what rules. A
    # provider that disagrees can say so against a specific hop.
    impact: dict[str, Any] = Field(default_factory=dict)
    # What must end up covered, rolled up to modules — the unit test
    # manifests and coverage reports already speak in. Derived from the
    # assessment's test obligations, so a relationship that propagates
    # without obliging a test (a deployment edge, say) widens the impact set
    # without demanding a scenario.
    #
    # An obligation, not an instruction. A provider may cover more, and may
    # cover less — but the difference is reconciled against what it reports,
    # so covering less is a disclosure rather than a silence.
    required_coverage: list[str] = Field(default_factory=list)
    # What must end up proven. A provider may exercise more; it may not
    # silently exercise less, and the gate checks the difference.
    criteria: list[dict[str, Any]] = Field(default_factory=list)
    # Where a pull request exists. Optional on purpose: a nightly regression
    # against a branch has no pull request, and a contract that demanded one
    # would forbid a legitimate run.
    change_request_id: str = ""
    contract_version: int = 1


class QAResult(BaseModel):
    """What was observed. Not what was intended.

    `assertions` is the load-bearing field. They are graph edges in the
    platform's own ontology — which criterion a scenario covers, which
    script exercised it, which run produced the evidence — and they are
    what turns "QA passed" into something a release decision can be
    audited against.
    """

    passed: bool = False
    # Free-form provider detail, shown to a human at the gate.
    summary: str = ""
    # Edges to ingest, as plain dicts. Dicts rather than models because the
    # producer is a separate package on the far side of a process boundary,
    # and a shared schema there is a coupling that would need versioning in
    # two places at once.
    assertions: list[dict[str, Any]] = Field(default_factory=list)
    # Where the evidence lives: a run URL, an artifact reference, a report.
    evidence_ref: str = ""
    # Which criteria the provider claims to have exercised, and which it
    # could not. Reported separately from `passed` because "everything I ran
    # passed" and "everything that needed running ran" are different claims,
    # and only the second one is a release decision.
    covered_criteria: list[str] = Field(default_factory=list)
    uncovered_criteria: list[str] = Field(default_factory=list)
    # The accounting against `required_coverage`. The platform hands down an
    # obligation and deterministic code checks it back; a provider free to
    # widen or narrow scope without reporting what it settled on would make
    # the obligation advisory, and an advisory control is not one.
    #
    # Empty is not the same as "nothing was covered" — a provider whose
    # capabilities say reports_coverage is false cannot answer this, and the
    # phase records the coverage half of the gate as not evaluated rather
    # than reading silence as a failure.
    covered_modules: list[str] = Field(default_factory=list)
    uncovered_modules: list[str] = Field(default_factory=list)
    detail: str = ""


class QAOutcome(BaseModel):
    """Either a result or a receipt.

    The same shape DesignAgent, ImplementationAgent and BuildDeploy use, so
    the phase branches on the state rather than on which provider is
    configured.
    """

    state: Literal["ready", "pending", "failed"]
    result: QAResult | None = None
    provider: str = ""
    # For the dispatched shape: what the WorkDispatch provider should be
    # started with. The phase owns the dispatch row and does the triggering;
    # a provider that triggered on its own would start remote work the
    # platform has no row for.
    dispatch_inputs: dict[str, Any] = Field(default_factory=dict)
    detail: str = ""


class QAAgent(Protocol):
    contract_version: int

    def capabilities(self) -> dict[str, Any]: ...
    """What this provider does, read before it is asked.

    Keys: dispatched (bool), authors_tests (bool), manages_test_data (bool),
    reports_coverage (bool).

    `reports_coverage` is the one that changes behaviour. A provider that
    cannot say which criteria it exercised gives the release gate nothing to
    check a claim against, and the phase records that the coverage half of
    the gate was not evaluated rather than treating silence as full
    coverage.
    """

    async def execute(self, request: QARequest) -> QAOutcome: ...

    def read_result(self, payload: dict[str, Any]) -> QAResult: ...
    """Interpret a finished dispatch.

    Separate because the two run in different processes: a QA run outlives
    the request that started it and is resumed by the reconciler with
    nothing but the payload."""
