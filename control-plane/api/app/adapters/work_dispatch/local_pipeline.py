"""Run the QA pipeline on this machine, against a real branch.

The local stub returns a canned result, which is enough to exercise the
dispatch seam but not enough to demonstrate a cycle: nothing is actually
tested. This adapter runs the real execution-plane pipeline as a subprocess
against the working copy, diffing the branch the implementation phase just
created — so regression scope is derived from the actual change.

It is a laptop convenience and says so. Running the execution plane from the
control-plane process is exactly the separation the two-job split exists to
maintain; in a deployed system this is the GitHub Actions adapter's job. What
makes it tolerable here is that the code being executed is the client's own
working copy, already on the same disk.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from app.ports.work_dispatch import DispatchHandle, DispatchResult


class LocalPipelineWorkDispatch:
    def __init__(
        self, repo_root: Path, base_ref: str = "main", secrets: dict[str, str] | None = None
    ) -> None:
        self._root = Path(repo_root)
        self._base = base_ref
        # The pipeline calls a model, and a subprocess does not inherit what
        # pydantic-settings read out of .env — that lands in Settings, not in
        # the environment. CI passes secrets to a job explicitly; so does this.
        self._secrets = {k: v for k, v in (secrets or {}).items() if v}
        self._runs: dict[str, dict[str, Any]] = {}

    @property
    def _qa_dir(self) -> Path:
        return self._root / "execution-plane" / "qa"

    @property
    def _python(self) -> Path:
        return self._qa_dir / ".venv" / "bin" / "python"

    def _git(self, *args: str) -> str:
        result = subprocess.run(
            ["git", *args], cwd=self._root, capture_output=True, text=True
        )
        if result.returncode != 0:
            raise RuntimeError(f"git {' '.join(args)}: {result.stderr.strip()}")
        return result.stdout.strip()

    def _checkout(self, branch: str, into: Path) -> Path:
        """A worktree of the branch, built and ready to serve.

        Testing the change means testing the change. Running against the
        working copy diffs the branch and then exercises whatever is on disk,
        which is the code before it. A worktree is how CI would do it, without
        disturbing what the person at this machine has checked out.
        """
        self._git("worktree", "add", "--detach", str(into), branch)
        app = into / "demo-app"

        # Dependencies are identical to the ones already installed; a symlink
        # turns a two-minute install into nothing.
        modules = self._root / "demo-app" / "node_modules"
        if modules.exists() and not (app / "node_modules").exists():
            (app / "node_modules").symlink_to(modules)

        build = subprocess.run(
            ["npm", "run", "build"], cwd=app, capture_output=True, text=True
        )
        if build.returncode != 0:
            raise RuntimeError(
                "the change does not build: " + (build.stdout or build.stderr)[-500:]
            )
        return app

    async def trigger(
        self, run_id: str, phase: str, correlation_id: str, inputs: dict[str, Any]
    ) -> DispatchHandle:
        if not self._python.exists():
            raise RuntimeError(
                f"{self._python} is missing — run ./run.sh qa once to build the "
                f"pipeline environment."
            )

        head = inputs.get("branch") or "HEAD"
        workspace = Path(tempfile.mkdtemp(prefix="qa-"))
        state_file = workspace / "qa-state.json"
        app_root = self._checkout(head, workspace / "checkout")

        process = subprocess.Popen(
            [
                str(self._python), "-m", "orchestrator.run",
                "--phase", "run",
                "--state-file", str(state_file),
                "--repo", "local/working-copy",
                "--pr-number", "0",
                "--base-sha", self._base,
                "--head-sha", head,
            ],
            cwd=self._qa_dir,
            env={**os.environ, **self._secrets, "QA_APP_ROOT": str(app_root)},
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        self._runs[correlation_id] = {
            "process": process, "state_file": state_file, "head": head,
            "workspace": workspace,
        }
        return DispatchHandle(
            provider="local-pipeline",
            correlation_id=correlation_id,
            external_id=str(process.pid),
        )

    async def check(self, handle: DispatchHandle) -> DispatchResult:
        entry = self._runs.get(handle.correlation_id)
        if entry is None:
            return DispatchResult(state="failed", detail="no local run for this dispatch")

        process: subprocess.Popen = entry["process"]
        if process.poll() is None:
            return DispatchResult(state="pending", external_id=handle.external_id)

        state_file: Path = entry["state_file"]
        if not state_file.exists():
            # Surface what the pipeline actually said. A dispatch that fails
            # with "no state file" and nothing else is a dead end for whoever
            # has to work out why.
            tail = (process.stdout.read() if process.stdout else "") or ""
            entry["output"] = tail
            last = [line for line in tail.strip().splitlines() if line.strip()][-3:]
            return DispatchResult(
                state="failed",
                detail="the pipeline produced no state file: " + " / ".join(last)[-500:],
                external_id=handle.external_id,
            )

        payload = json.loads(state_file.read_text())
        self._keep_evidence(entry)
        self._cleanup(entry)
        return DispatchResult(
            state="succeeded" if payload.get("gate_passed") else "failed",
            payload=payload,
            evidence_ref=str(self._root / "evidence" / "html-report" / "index.html"),
            detail=None if payload.get("gate_passed") else "; ".join(payload.get("gate_reasons", [])),
            external_id=handle.external_id,
        )

    def _keep_evidence(self, entry: dict[str, Any]) -> None:
        """Copy screenshots, traces and the report out of the worktree.

        They are written beside the checkout under test and the checkout is
        about to be deleted — evidence nobody can open afterwards is not
        evidence.
        """
        workspace = entry.get("workspace")
        if not workspace:
            return
        produced = Path(workspace) / "checkout" / "evidence"
        if not produced.is_dir():
            return
        kept = self._root / "evidence"
        shutil.rmtree(kept, ignore_errors=True)
        shutil.copytree(produced, kept, symlinks=False, dirs_exist_ok=True)

    def _cleanup(self, entry: dict[str, Any]) -> None:
        workspace = entry.get("workspace")
        if not workspace:
            return
        checkout = Path(workspace) / "checkout"
        # Remove the symlink before git does, or `worktree remove` walks into
        # the real node_modules and takes minutes to decide it is not empty.
        link = checkout / "demo-app" / "node_modules"
        if link.is_symlink():
            link.unlink()
        subprocess.run(
            ["git", "worktree", "remove", "--force", str(checkout)],
            cwd=self._root, capture_output=True, text=True,
        )
        shutil.rmtree(workspace, ignore_errors=True)
