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

# .../control-plane/api/app/adapters/work_dispatch/local_pipeline.py
# -> the repository root, five levels up. Counted rather than guessed:
# getting it wrong resolves to a directory that does not exist and the
# failure surfaces as a missing interpreter, which blames the wrong thing.
_PLATFORM_QA_ROOT = Path(__file__).resolve().parents[5] / "execution-plane" / "qa"


class LocalPipelineWorkDispatch:
    def __init__(
        self,
        repo_root: Path,
        base_ref: str = "main",
        secrets: dict[str, str] | None = None,
        *,
        qa_root: Path | None = None,
        app_subdir: str = "demo-app",
        build_command: str = "npm run build",
        qa_env: dict[str, str] | None = None,
    ) -> None:
        self._root = Path(repo_root)
        self._base = base_ref
        # Two roots, because they are two different things. The execution
        # plane is part of this platform; the application under test belongs
        # to the client. Deriving the first from the second meant the
        # orchestrator had to live inside the repository it was testing —
        # true only while the platform was testing its own sample app, and
        # false for every real checkout.
        self._qa_root = Path(qa_root) if qa_root else _PLATFORM_QA_ROOT
        self._app_subdir = app_subdir
        self._build_command = build_command
        # Where this application keeps the things the pipeline reads: its
        # script manifest, its generated specs, its route mocks. Passed
        # through rather than assumed, because assuming them is what tied the
        # adapter to one layout.
        self._qa_env = dict(qa_env or {})
        # The pipeline calls a model, and a subprocess does not inherit what
        # pydantic-settings read out of .env — that lands in Settings, not in
        # the environment. CI passes secrets to a job explicitly; so does this.
        self._secrets = {k: v for k, v in (secrets or {}).items() if v}
        self._runs: dict[str, dict[str, Any]] = {}

    @property
    def _qa_dir(self) -> Path:
        return self._qa_root

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
        app = into / self._app_subdir
        self._provide_dependencies(app)

        # An empty command means the app starts itself — a Playwright config
        # with a `webServer` block does, and building ahead of it is minutes
        # spent producing something nothing runs.
        if self._build_command:
            build = subprocess.run(
                self._build_command.split(), cwd=app, capture_output=True, text=True
            )
            if build.returncode != 0:
                raise RuntimeError(
                    "the change does not build: " + (build.stdout or build.stderr)[-500:]
                )
        return app

    def _provide_dependencies(self, app: Path) -> None:
        """node_modules in the worktree, without a fresh install.

        This used to symlink the working copy's. Next.js refuses that:
        Turbopack panics with "Symlink [project]/node_modules is invalid, it
        points out of the filesystem root" and the web server never starts,
        so every scenario fails for a reason that has nothing to do with the
        change under test. It worked for the sample app and would have failed
        on the first real one.

        A copy-on-write clone is the same trick the symlink was reaching for
        — 700MB in nine seconds on APFS, and no extra disk until something is
        written. `--reflink=auto` is the Linux equivalent and degrades to a
        real copy where the filesystem cannot. Falling all the way back to an
        install is slow but correct, which is the right order for the last
        resort.
        """
        target = app / "node_modules"
        source = self._root / self._app_subdir / "node_modules"
        if target.exists() or not source.exists():
            return

        for command in (
            ["cp", "-Rc", str(source), str(target)],          # APFS clonefile
            ["cp", "-R", "--reflink=auto", str(source), str(target)],  # GNU
            ["cp", "-R", str(source), str(target)],
        ):
            if subprocess.run(command, capture_output=True).returncode == 0:
                return

        install = subprocess.run(
            ["npm", "ci"], cwd=app, capture_output=True, text=True
        )
        if install.returncode != 0:
            raise RuntimeError(
                "could not provide node_modules for the checkout under test: "
                + (install.stderr or install.stdout)[-500:]
            )

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

        # A second checkout at the base revision, so the gate can tell a
        # regression from something that was already broken. Best-effort: a
        # base that will not check out or will not build costs the run its
        # baseline, and the gate then blocks every failing required script
        # and says the baseline was never established. That is the right
        # failure — the alternative is a missing baseline quietly excusing
        # everything.
        base = inputs.get("base_sha") or self._base
        base_root = None
        try:
            base_root = self._checkout(base, workspace / "base")
        except Exception:  # noqa: BLE001 - reported through the gate's own note
            base_root = None

        command = [
            str(self._python), "-m", "orchestrator.run",
            "--phase", "run",
            "--state-file", str(state_file),
            "--repo", inputs.get("repo") or "local/working-copy",
            "--pr-number", "0",
            "--base-sha", inputs.get("base_sha") or self._base,
            "--head-sha", head,
        ]
        # How far this change reaches, as the control plane assessed it. A
        # file rather than an argument because an assessment carries its
        # explanation — the hops, the blind spots, the policy — and a command
        # line is the wrong place for it. Absent, the run scopes to the edit
        # alone and says so rather than inventing a traversal.
        if inputs.get("impact"):
            impact_file = workspace / "impact.json"
            impact_file.write_text(json.dumps(inputs["impact"], indent=2))
            command += ["--impact", str(impact_file)]

        process = subprocess.Popen(
            command,
            cwd=self._qa_dir,
            env={
                **os.environ,
                **self._secrets,
                **{
                    # Relative to the checkout under test, not to the working
                    # copy: a run against a branch reads that branch's
                    # manifest and mocks, or it is scoping one revision by
                    # another revision's files.
                    key: str(app_root / value) if not Path(value).is_absolute() else value
                    for key, value in self._qa_env.items()
                },
                "QA_APP_ROOT": str(app_root),
                **({"QA_BASE_APP_ROOT": str(base_root)} if base_root else {}),
            },
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
