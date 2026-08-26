"""The client's QA automation, reached through the shared dispatch seam.

Hands over the contract and gets out of the way. Which scripts to reuse,
which to write, how to seed and tear down data, what runner to use — all of
that is the client's, and a platform that dictated them would be asking a
team with a mature QA estate to throw it away.

What comes back is not negotiable: which criteria were exercised and by
what, as edges in the platform's ontology. A provider that returns "passed"
and nothing else has reported an opinion.

Covers both the framework's own pipeline running remotely (GitHub Actions
executing the execution plane) and a wholly foreign one. From the control
plane's side those are the same thing — work started elsewhere, answered
later — which is why they are one adapter and not two.
"""

from __future__ import annotations

from typing import Any

from app.ports.qa_agent import QAOutcome, QARequest, QAResult


class DispatchedQAAgent:
    contract_version = 1

    def __init__(self, provider: str, dispatch: Any = None) -> None:
        self._provider = provider
        self._dispatch = dispatch

    def capabilities(self) -> dict[str, Any]:
        return {
            "dispatched": True,
            "authors_tests": True,
            "manages_test_data": True,
            # Whether it *does* is the provider's business; whether the
            # platform can check its claim is not. A provider that reports
            # no coverage leaves the coverage half of the release gate
            # unevaluated, and the phase records that rather than reading
            # silence as full coverage.
            "reports_coverage": True,
        }

    async def execute(self, request: QARequest) -> QAOutcome:
        return QAOutcome(
            state="pending",
            provider=self._provider,
            dispatch_inputs={
                "base_sha": request.base_sha,
                "head_sha": request.head_sha,
                "branch": request.branch,
                "repo": request.repo,
                # The changed set, not the blast radius. Named here rather
                # than left to a convention in the phase: a provider that
                # mistook one for the other would scope its regression
                # selection to exactly the files that were edited and miss
                # everything downstream.
                "changed_paths": request.changed_paths,
                "change_request_id": request.change_request_id,
                "contract_version": request.contract_version,
            },
        )

    def read_result(self, payload: dict[str, Any]) -> QAResult:
        """What a finished QA run means.

        Tolerant of a provider that answers less than the full contract —
        a missing coverage list is reported as missing, not inferred. The
        one thing it will not do is invent a pass.
        """
        return QAResult(
            passed=bool(payload.get("passed", False)),
            summary=str(payload.get("summary") or ""),
            assertions=list(payload.get("assertions") or []),
            evidence_ref=str(payload.get("evidence_ref") or ""),
            covered_criteria=list(payload.get("covered_criteria") or []),
            uncovered_criteria=list(payload.get("uncovered_criteria") or []),
            detail=str(payload.get("detail") or ""),
        )
