"""The environment agent-written specs are allowed to run in.

validate.py has always been honest that it is a text scan and not a sandbox,
and it named the real control: the privilege split in the CI workflow, where
the job executing generated specs holds no write token. That argument was
sound for CI and does not survive the local adapter, which runs the pipeline
as a subprocess of the control plane — inheriting the whole developer
environment, model key included, and then handing it to `npx playwright
test`. A generated spec ran with the credentials of whoever started the run.

So the runner builds the environment rather than inheriting one. What a
browser test legitimately needs is small and nameable; everything else is
somebody's credential until proven otherwise.

Allowlist rather than denylist, deliberately. A denylist has to anticipate
the name of every secret a client happens to export, and the one it has not
heard of is exactly the one that leaks. This way a variable a test genuinely
needs is added by whoever knows why, which is a conversation worth having.
"""

from __future__ import annotations

import os

# What a browser process needs to exist at all, plus what Playwright and
# Node read to behave. Nothing here identifies anybody.
PASSTHROUGH = frozenset(
    {
        "PATH", "HOME", "TMPDIR", "TEMP", "TMP", "SHELL", "USER", "LOGNAME",
        "LANG", "LC_ALL", "TZ",
        "CI", "FORCE_COLOR", "NO_COLOR", "TERM", "COLUMNS",
        "NODE_OPTIONS", "NODE_ENV", "npm_config_cache",
        "DISPLAY", "XDG_RUNTIME_DIR", "XAUTHORITY",
        "SystemRoot", "COMSPEC", "PATHEXT", "USERPROFILE", "APPDATA",
        "LOCALAPPDATA", "ProgramFiles", "ProgramData", "windir",
    }
)

# Prefixes a test may need for the app under test to boot: Playwright's own
# configuration, and this pipeline's paths. Never a bare `NEXT_` or `VITE_`
# prefix — client frameworks put live API keys behind those.
PASSTHROUGH_PREFIXES = ("PLAYWRIGHT_", "QA_")


def for_specs(overrides: dict[str, str] | None = None) -> dict[str, str]:
    """A minimal environment, plus whatever the caller deliberately adds.

    `overrides` is the test-data provider's lease env — values this pipeline
    generated for this run, so they are additions rather than inheritance.
    """
    env = {
        key: value
        for key, value in os.environ.items()
        if key in PASSTHROUGH or key.startswith(PASSTHROUGH_PREFIXES)
    }
    env.update(overrides or {})
    return env


def withheld(overrides: dict[str, str] | None = None) -> list[str]:
    """Which variable names were dropped, for the run to report.

    Names only, never values. A run that silently narrowed the environment is
    hard to debug when a test needs something legitimate — and a list of
    names is enough to see what happened without printing a secret to a log
    that CI uploads.
    """
    kept = set(for_specs(overrides))
    return sorted(k for k in os.environ if k not in kept)
