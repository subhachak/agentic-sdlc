"""The shipped TestRunner: Playwright, as the run node used to invoke it.

Unchanged behaviour, moved behind the port. It returns the raw results
document rather than a parsed one, because parsing belongs to whoever knows
Playwright's format — and a runner that pre-digested its own results could
hide a failure by returning a shape the gate reads as empty.
"""

from __future__ import annotations

import json
import os
import subprocess
from typing import Any

from orchestrator.paths import APP_ROOT, RESULTS_FILE
from orchestrator.ports_execution import EXECUTION_CONTRACT_VERSION


class PlaywrightRunner:
    contract_version = EXECUTION_CONTRACT_VERSION
    name = "playwright"

    def supports_parallel(self) -> bool:
        return True

    def execute(
        self,
        *,
        specs: list[str],
        workers: int,
        env: dict[str, str],
        evidence_dir: str,
    ) -> dict[str, Any]:
        command = ["npx", "playwright", "test"]
        # 0 means "the runner's own default", which is not the same as
        # asking for zero workers.
        if workers:
            command.append(f"--workers={workers}")

        # One project unless told otherwise. Fronei declares `chromium` and
        # `mobile-chrome`, so an unqualified run executes every spec twice —
        # doubling the time and grading authored scenarios against a mobile
        # viewport nobody wrote them for. Their own CI pins `--project` for
        # the same reason; the pipeline should not be less specific than the
        # suite it is running.
        project = os.environ.get("QA_PLAYWRIGHT_PROJECT", "")
        if project:
            command.append(f"--project={project}")

        # The specs this run actually assigned. Without them Playwright
        # collects whatever `testDir` holds, so the blast radius decided what
        # was *reported* while the suite decided what was *run* — and the
        # claim that scoping selected these tests was not true of execution.
        command.extend(specs)

        proc = subprocess.run(
            command,
            cwd=APP_ROOT,
            capture_output=True,
            text=True,
            env={**os.environ, **env},
        )
        if RESULTS_FILE.exists():
            return json.loads(RESULTS_FILE.read_text())
        # The absence of a results file is itself the result, and carrying
        # the streams is what makes it diagnosable.
        return {
            "error": "no results.json produced",
            "exit_code": proc.returncode,
            "stdout": proc.stdout[-4000:],
            "stderr": proc.stderr[-4000:],
        }
