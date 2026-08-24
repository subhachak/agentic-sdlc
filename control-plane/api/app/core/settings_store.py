"""Configuration that lives in the control plane, not only in a .env file.

Three kinds of setting, treated differently on purpose:

  mutable  — adapter choices and thresholds. Editable here, persisted as an
             override, and applied by rebuilding the adapters; the registry is
             already a pure function of settings, so that is all it takes.
  secret   — API keys and tokens. Reported as present or absent and never
             returned or accepted. They stay in the environment rather than
             being written to a database in plaintext, which is the honest
             thing to do until there is a secrets manager behind a port.
  static   — values the process is built around, such as the database URL.
             Shown for orientation, changed by restarting.

Every change is written to the audit trail. Switching the model provider
mid-programme is exactly the kind of act a governed platform should be able
to account for afterwards.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from sqlalchemy import delete, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.core.config import Settings
from app.core.db import get_sessionmaker
from app.models.setting import SettingChange, SettingOverride

Kind = Literal["mutable", "secret", "static"]
ValueType = Literal["enum", "text", "int", "float", "bool"]


@dataclass(frozen=True)
class SettingSpec:
    key: str
    label: str
    group: str
    kind: Kind = "mutable"
    type: ValueType = "text"
    options: tuple[str, ...] = ()
    help: str = ""
    placeholder: str = ""


SPECS: tuple[SettingSpec, ...] = (
    # --- agents ---
    SettingSpec("llm_provider_adapter", "Model provider", "Agents", type="enum",
                options=("mock", "claude"),
                help="mock runs the pipeline with no API key and no network."),
    SettingSpec("claude_model", "Claude model", "Agents",
                placeholder="claude-opus-5"),
    SettingSpec("anthropic_api_key", "Anthropic API key", "Agents", kind="secret",
                help="Read from the environment. Required when the provider is claude."),
    SettingSpec("max_node_retries", "Node retries", "Agents", type="int",
                help="Business nodes only. Gates and dispatches are never retried."),

    # --- governance ---
    SettingSpec("auto_approve_gates", "Auto-approve human gates", "Governance", type="bool",
                help="Skips the three human gates for headless runs. Never skips the "
                     "QA execution pause — a job that has not run has no result to approve."),

    # --- remote execution ---
    SettingSpec("work_dispatch_adapter", "Execution target", "Remote execution", type="enum",
                options=("local", "local-pipeline", "github-actions"),
                help="local simulates a job; local-pipeline runs the real QA pipeline "
                     "against the working copy; github-actions dispatches to CI."),
    SettingSpec("github_repo", "Repository", "Remote execution",
                placeholder="owner/name"),
    SettingSpec("github_workflow_file", "Workflow file", "Remote execution",
                placeholder="agentic-qa.yml"),
    SettingSpec("github_ref", "Ref", "Remote execution", placeholder="main"),
    SettingSpec("github_token", "GitHub token", "Remote execution", kind="secret",
                help="Needs actions:write to dispatch and actions:read to fetch results."),
    SettingSpec("dispatch_timeout_seconds", "Dispatch timeout (s)", "Remote execution", type="int",
                help="How long a dispatched phase may run before the run is failed."),
    SettingSpec("reconciler_interval_seconds", "Reconciler interval (s)", "Remote execution",
                type="float"),
    SettingSpec("local_dispatch_duration_seconds", "Simulated job duration (s)",
                "Remote execution", type="float"),

    # --- implementation ---
    SettingSpec("source_control_adapter", "Change target", "Implementation", type="enum",
                options=("local", "github"),
                help="local writes a branch in a working copy and pushes nothing."),
    SettingSpec("target_repo", "Repository", "Implementation", placeholder="owner/name"),
    SettingSpec("target_ref", "Base branch", "Implementation", placeholder="main"),
    SettingSpec("target_working_copy", "Working copy", "Implementation",
                help="Used when the change target is local."),
    SettingSpec("target_environment", "Deploy environment", "Implementation",
                placeholder="staging"),

    # --- context graph ---
    SettingSpec("code_intelligence_adapter", "Index source", "Context graph", type="enum",
                options=("github", "local"),
                help="Where the code graph is derived from."),
    SettingSpec("code_index_repo", "Repository to index", "Context graph",
                placeholder="owner/name"),
    SettingSpec("code_index_ref", "Ref to index", "Context graph", placeholder="main"),
    SettingSpec("code_index_max_depth", "Component depth", "Context graph", type="int",
                help="A component is a directory collapsed to this many path segments."),
    SettingSpec("code_index_local_root", "Local path", "Context graph",
                help="Used when the index source is local."),

    # --- platform ---
    SettingSpec("database_url", "Database", "Platform", kind="static"),
    SettingSpec("web_origin", "Console origin", "Platform", kind="static"),
)

BY_KEY = {spec.key: spec for spec in SPECS}
MUTABLE_KEYS = frozenset(s.key for s in SPECS if s.kind == "mutable")


class ConfigError(ValueError):
    pass


async def load_overrides() -> dict[str, Any]:
    async with get_sessionmaker()() as session:
        rows = (await session.execute(select(SettingOverride))).scalars().all()
    return {row.key: row.value for row in rows}


def effective(base: Settings, overrides: dict[str, Any]) -> Settings:
    """Settings as the platform should behave right now.

    Built by re-validating rather than by mutating, so an override that would
    produce an invalid configuration is rejected here rather than surfacing as
    a confusing failure inside an adapter.
    """
    applicable = {k: v for k, v in overrides.items() if k in MUTABLE_KEYS}
    if not applicable:
        return base
    return Settings(**{**base.model_dump(), **applicable})


def _coerce(spec: SettingSpec, raw: Any) -> Any:
    if raw is None or raw == "":
        return None
    try:
        if spec.type == "int":
            return int(raw)
        if spec.type == "float":
            return float(raw)
        if spec.type == "bool":
            return raw if isinstance(raw, bool) else str(raw).lower() in ("1", "true", "yes", "on")
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{spec.key}: expected {spec.type}, got {raw!r}") from exc

    value = str(raw)
    if spec.options and value not in spec.options:
        raise ConfigError(f"{spec.key}: must be one of {', '.join(spec.options)}")
    return value


def validate(changes: dict[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key, raw in changes.items():
        spec = BY_KEY.get(key)
        if spec is None:
            raise ConfigError(f"unknown setting {key!r}")
        if spec.kind == "secret":
            raise ConfigError(
                f"{key} is a secret and is set in the environment, never through the API"
            )
        if spec.kind == "static":
            raise ConfigError(f"{key} cannot be changed while the process is running")
        cleaned[key] = _coerce(spec, raw)
    return cleaned


async def history(limit: int = 20) -> list[dict[str, Any]]:
    async with get_sessionmaker()() as session:
        rows = (
            await session.execute(
                select(SettingChange).order_by(SettingChange.created_at.desc()).limit(limit)
            )
        ).scalars().all()
    return [
        {
            "key": r.key,
            "label": BY_KEY[r.key].label if r.key in BY_KEY else r.key,
            "previous": r.previous,
            "value": r.value,
            "changed_by": r.changed_by,
            "at": r.created_at.isoformat(),
        }
        for r in rows
    ]


async def save(changes: dict[str, Any], updated_by: str = "console") -> dict[str, Any]:
    """Persist overrides, recording what each value was before.

    A value of None clears the override, restoring the environment default
    rather than storing an empty one.
    """
    cleaned = validate(changes)
    previous = await load_overrides()

    async with get_sessionmaker()() as session:
        for key, value in cleaned.items():
            session.add(
                SettingChange(
                    key=key,
                    previous=previous.get(key),
                    value=value,
                    changed_by=updated_by,
                )
            )
            if value is None:
                await session.execute(delete(SettingOverride).where(SettingOverride.key == key))
                continue
            await session.execute(
                sqlite_insert(SettingOverride)
                .values(key=key, value=value, updated_by=updated_by)
                .on_conflict_do_update(
                    index_elements=[SettingOverride.key],
                    set_={"value": value, "updated_by": updated_by},
                )
            )
        await session.commit()

    return cleaned


def describe(base: Settings, overrides: dict[str, Any]) -> list[dict[str, Any]]:
    """The settings as the console should render them.

    Secrets report presence only. Everything else reports its effective value
    and whether that came from an override or from the environment.
    """
    current = effective(base, overrides)
    out: list[dict[str, Any]] = []

    for spec in SPECS:
        entry: dict[str, Any] = {
            "key": spec.key,
            "label": spec.label,
            "group": spec.group,
            "kind": spec.kind,
            "type": spec.type,
            "options": list(spec.options),
            "help": spec.help,
            "placeholder": spec.placeholder,
            "overridden": spec.key in overrides and spec.kind == "mutable",
        }
        if spec.kind == "secret":
            entry["configured"] = bool(getattr(current, spec.key, None))
            entry["value"] = None
        else:
            entry["value"] = getattr(current, spec.key, None)
        out.append(entry)

    return out
