"""GitHub Actions adapter.

Results are pulled, never pushed. The control plane asks GitHub what
happened using its own credential, so nothing a stranger can send becomes
run state — there is no callback signature to verify and no shared secret to
rotate. It also means this works unchanged on a laptop, where GitHub could
not reach a local callback URL anyway.

`workflow_dispatch` returns no run id, so trigger() plants a correlation
nonce in the workflow inputs and check() resolves the run by matching the
nonce against recent runs of that workflow.

A workflow that emits a qa-state artifact gives full detail: scenarios,
evidence and the graph edges the run observed. A workflow that knows nothing
about this platform still gives a conclusion, and that is enough to govern a
run — so an existing CI pipeline can be driven without being modified first.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.ports.work_dispatch import DispatchHandle, DispatchResult

_API = "https://api.github.com"
_TIMEOUT = 30.0


class GitHubActionsWorkDispatch:
    def __init__(
        self,
        *,
        repo: str,
        token: str,
        workflow_file: str = "agentic-qa.yml",
        ref: str = "main",
    ) -> None:
        self._repo = repo
        self._token = token
        self._workflow = workflow_file
        self._ref = ref

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    async def trigger(
        self, run_id: str, phase: str, correlation_id: str, inputs: dict[str, Any]
    ) -> DispatchHandle:
        head_sha = str(inputs.get("head_sha", "")).strip()
        if not head_sha:
            # `workflow_dispatch` cannot decline a run for missing inputs — it
            # would start, check out the workflow's own ref, and report a
            # verdict on the default branch. That reads exactly like a passing
            # QA result for a change it never saw, so the refusal has to
            # happen here, before anything is triggered.
            raise ValueError(
                "refusing to dispatch a QA run with no head revision: the executor "
                "would test its default branch instead of the change"
            )

        body = {
            # Which workflow definition to run. The revision *under test*
            # travels in the inputs — the workflow checks that out itself,
            # because the two are not the same thing and conflating them is
            # how a run ends up testing the branch the workflow lives on.
            "ref": self._ref,
            "inputs": {
                "control_run_id": run_id,
                "correlation_id": correlation_id,
                "base_sha": str(inputs.get("base_sha", "")),
                "head_sha": head_sha,
            },
        }
        url = f"{_API}/repos/{self._repo}/actions/workflows/{self._workflow}/dispatches"
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(url, headers=self._headers, json=body)
            resp.raise_for_status()
        return DispatchHandle(provider="github-actions", correlation_id=correlation_id)

    async def check(self, handle: DispatchHandle) -> DispatchResult:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            run = await self._resolve_run(client, handle)
            if run is None:
                # Queued but not yet visible in the runs list.
                return DispatchResult(state="pending")

            if run["status"] != "completed":
                return DispatchResult(
                    state="pending", external_id=str(run["id"]), external_url=run["html_url"]
                )

            common = {"external_id": str(run["id"]), "external_url": run["html_url"]}
            if run["conclusion"] != "success":
                return DispatchResult(
                    state="failed", detail=f"workflow concluded {run['conclusion']}", **common
                )

            artifact = await self._find_artifact(client, run["id"], handle.correlation_id)
            if artifact is None:
                # A workflow that does not know about this platform still gives
                # a verdict: it either passed or it did not. Reporting that as
                # a failure would mean any repository with existing CI had to
                # adopt our state artifact before it could be governed at all.
                # The result is thinner — a conclusion, no scenarios and no
                # traceability edges — and says so.
                return DispatchResult(
                    state="succeeded",
                    payload={
                        "gate_passed": True,
                        "gate_reasons": [
                            f"workflow {run.get('name') or self._workflow} concluded success"
                        ],
                        "test_plan": [],
                        "assertions": [],
                        "evidence_summary": {"html_report": run["html_url"]},
                        "detail": "no state artifact — conclusion only, no scenario detail",
                    },
                    evidence_ref=run["html_url"],
                    detail="conclusion only: the workflow produced no state artifact",
                    **common,
                )
            return DispatchResult(
                state="succeeded",
                payload=await self._download_state(client, artifact["archive_download_url"]),
                evidence_ref=run["html_url"],
                **common,
            )

    async def _resolve_run(self, client: httpx.AsyncClient, handle: DispatchHandle) -> dict | None:
        if handle.external_id:
            resp = await client.get(
                f"{_API}/repos/{self._repo}/actions/runs/{handle.external_id}",
                headers=self._headers,
            )
            resp.raise_for_status()
            return resp.json()

        resp = await client.get(
            f"{_API}/repos/{self._repo}/actions/workflows/{self._workflow}/runs",
            headers=self._headers,
            params={"event": "workflow_dispatch", "per_page": 30},
        )
        resp.raise_for_status()
        # The job echoes the nonce into its run name, which is the only way
        # to tie a workflow_dispatch call to the run it created.
        for run in resp.json().get("workflow_runs", []):
            if handle.correlation_id in (run.get("name") or ""):
                return run
        return None

    async def _find_artifact(
        self, client: httpx.AsyncClient, run_id: int, correlation_id: str
    ) -> dict | None:
        resp = await client.get(
            f"{_API}/repos/{self._repo}/actions/runs/{run_id}/artifacts", headers=self._headers
        )
        resp.raise_for_status()
        artifacts = resp.json().get("artifacts", [])
        for artifact in artifacts:
            if correlation_id in artifact["name"]:
                return artifact
        return next((a for a in artifacts if a["name"].startswith("qa-state")), None)

    async def _download_state(self, client: httpx.AsyncClient, url: str) -> dict:
        import io
        import json
        import zipfile

        resp = await client.get(url, headers=self._headers, follow_redirects=True)
        resp.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(resp.content)) as archive:
            name = next(n for n in archive.namelist() if n.endswith(".json"))
            return json.loads(archive.read(name))
