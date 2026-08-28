"""Agent-written specs do not run with the caller's credentials.

validate.py was always honest that it is a text scan rather than a sandbox,
and it named the real control: the CI privilege split, where the job that
executes generated specs holds no write token. That argument was sound for CI
and did not survive the local adapter, which runs the pipeline as a
subprocess of the control plane — inheriting the whole developer environment,
model key included, and handing it to `npx playwright test`.

A regex ban on `process.env` was the only thing in the way, in a file whose
own docstring says a determined author can phrase around it.
"""

from __future__ import annotations

from orchestrator import runner_env


SECRETS = {
    "ANTHROPIC_API_KEY": "sk-ant-not-a-real-key",
    "GITHUB_TOKEN": "ghp_not-a-real-token",
    "JIRA_API_TOKEN": "not-a-real-token",
    "AWS_SECRET_ACCESS_KEY": "not-a-real-key",
    "DATABASE_URL": "postgres://user:pw@host/db",
}


def test_no_credential_reaches_a_generated_spec(monkeypatch):
    for key, value in SECRETS.items():
        monkeypatch.setenv(key, value)
    env = runner_env.for_specs()
    for key in SECRETS:
        assert key not in env, f"{key} reached the spec environment"


def test_what_a_browser_actually_needs_survives(monkeypatch):
    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setenv("HOME", "/home/x")
    monkeypatch.setenv("CI", "true")
    env = runner_env.for_specs()
    assert env["PATH"] == "/usr/bin"
    assert env["HOME"] == "/home/x"
    assert env["CI"] == "true"


def test_the_pipelines_own_configuration_passes(monkeypatch):
    monkeypatch.setenv("PLAYWRIGHT_BASE_URL", "http://127.0.0.1:3100")
    monkeypatch.setenv("QA_APP_ROOT", "/tmp/checkout")
    env = runner_env.for_specs()
    assert env["PLAYWRIGHT_BASE_URL"] == "http://127.0.0.1:3100"
    assert env["QA_APP_ROOT"] == "/tmp/checkout"


def test_a_lease_is_an_addition_not_an_inheritance(monkeypatch):
    """The provider generated these values for this run, so they are the one
    thing the pipeline is entitled to hand across."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-nope")
    env = runner_env.for_specs({"QA_SCENARIO_SCOPE": "run-1"})
    assert env["QA_SCENARIO_SCOPE"] == "run-1"
    assert "ANTHROPIC_API_KEY" not in env


# ── why an allowlist ──────────────────────────────────────────────────────


def test_an_unknown_variable_is_dropped_rather_than_judged(monkeypatch):
    """A denylist has to anticipate the name of every secret a client happens
    to export, and the one it has not heard of is exactly the one that
    leaks."""
    monkeypatch.setenv("ACME_INTERNAL_SIGNING_SECRET", "nope")
    monkeypatch.setenv("SOME_HARMLESS_THING", "fine")
    env = runner_env.for_specs()
    assert "ACME_INTERNAL_SIGNING_SECRET" not in env
    assert "SOME_HARMLESS_THING" not in env


def test_framework_public_prefixes_are_not_blanket_allowed(monkeypatch):
    """NEXT_PUBLIC_ and VITE_ look safe and routinely carry live keys —
    analytics, Sentry, Stripe publishable keys, and often worse by accident."""
    monkeypatch.setenv("NEXT_PUBLIC_SENTRY_DSN", "https://x@y/1")
    monkeypatch.setenv("VITE_API_KEY", "nope")
    env = runner_env.for_specs()
    assert "NEXT_PUBLIC_SENTRY_DSN" not in env
    assert "VITE_API_KEY" not in env


def test_the_run_can_say_what_it_withheld_without_printing_it(monkeypatch):
    """A silently narrowed environment is hard to debug when a test needs
    something legitimate. Names are enough to see what happened; values would
    be a secret in a log that CI uploads."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-nope")
    names = runner_env.withheld()
    assert "ANTHROPIC_API_KEY" in names
    assert all("sk-ant" not in n for n in names)


def test_the_runner_uses_it(monkeypatch, tmp_path):
    """The allowlist is worth nothing if the runner still inherits."""
    import orchestrator.adapters.playwright_runner as runner

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-nope")
    captured = {}

    class _Result:
        returncode = 0
        stdout = stderr = ""

    monkeypatch.setattr(
        runner.subprocess, "run",
        lambda command, **kw: (captured.update(env=kw.get("env") or {}), _Result())[1],
    )
    monkeypatch.setattr(runner, "RESULTS_FILE", tmp_path / "absent.json")
    runner.PlaywrightRunner().execute(specs=[], workers=1, env={}, evidence_dir="/tmp")

    assert "ANTHROPIC_API_KEY" not in captured["env"]
    assert "PATH" in captured["env"]
