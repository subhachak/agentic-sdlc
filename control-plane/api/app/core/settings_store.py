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

from app.core.config import Settings, undone
from app.core.db import get_sessionmaker
from app.models.setting import SettingChange, SettingOverride

Kind = Literal["mutable", "secret", "static"]
ValueType = Literal["enum", "text", "int", "float", "bool"]
# The axis that decides who changes a setting and how often.
#
#   engagement — what this deployment is pointed at: repositories, branches,
#                environments, how coarse a module is in *this* codebase.
#                Changes per client and per project, and is the first thing
#                anyone touches on a new engagement.
#   platform   — how the platform itself runs: which adapters, which model,
#                retry and gate policy. Changes per deployment, rarely.
#   credential — secrets. Never read back, only reported as present.
#
# Separated because presenting them as one list makes a client-specific
# repository name look like a platform decision, and buries the four fields
# someone actually needs to fill in among twenty they should not touch.
Section = Literal["engagement", "platform", "credential"]


@dataclass(frozen=True)
class SettingSpec:
    key: str
    label: str
    group: str
    section: Section = "platform"
    kind: Kind = "mutable"
    type: ValueType = "text"
    options: tuple[str, ...] = ()
    help: str = ""
    placeholder: str = ""
    # Where this comes from when nobody sets it. A field with a source is an
    # override, not a question — the console keeps it out of the way and
    # shows what it resolved to, rather than presenting an empty box that
    # looks like something someone forgot.
    derived_from: str = ""
    # Set somewhere other than this page. Shown read-only with a pointer,
    # because two controls writing one value is how they drift apart.
    owned_by: str = ""
    # (key, value) — only worth asking when another setting says so. A
    # working copy path is meaningless when the change target is GitHub, and
    # a field that cannot affect anything is still a field someone reads.
    relevant_when: tuple[str, str] = ()
    # Has a working default and exists for tuning. Kept out of the way
    # rather than off the page: "only ask what cannot be derived" is about
    # what is presented first, not about removing control.
    advanced: bool = False


SPECS: tuple[SettingSpec, ...] = (
    # --- agents ---
    SettingSpec("llm_provider_adapter", "Model provider", "Agents", type="enum",
                options=("mock", "claude"),
                help="mock runs the pipeline with no API key and no network."),
    SettingSpec("claude_model", "Claude model", "Agents",
                placeholder="claude-opus-5"),
    SettingSpec("anthropic_api_key", "Anthropic API key", "Credentials", section="credential", kind="secret",
                help="Read from the environment. Required when the provider is claude."),
    SettingSpec("max_node_retries", "Node retries", "Agents", type="int",
                help="Business nodes only. Gates and dispatches are never retried."),

    SettingSpec("active_project", "Active project", "Engagement", section="platform",
                help="Which engagement the platform is working on. The graph is scoped "
                     "by it, and this project's own settings overlay the defaults."),

    # --- governance ---
    SettingSpec("auto_approve_gates", "Auto-approve human gates", "Governance", type="bool",
                help="Skips the three human gates for headless runs. Never skips the "
                     "QA execution pause — a job that has not run has no result to approve."),

    # --- remote execution ---
    SettingSpec("work_dispatch_adapter", "Execution target", "Remote execution", type="enum",
                options=("local", "local-pipeline", "github-actions"),
                help="local simulates a job; local-pipeline runs the real QA pipeline "
                     "against the working copy; github-actions dispatches to CI."),
    SettingSpec("github_repo", "CI repository", "Delivery targets", section="engagement",
                placeholder="owner/name", derived_from="code_index_repo",
                help="Only when the workflow lives somewhere other than the repository "
                     "being indexed."),
    SettingSpec("github_workflow_file", "Workflow file", "Delivery targets", section="engagement",
                placeholder="agentic-qa.yml", advanced=True,
                relevant_when=("work_dispatch_adapter", "github-actions"),
                help="The workflow the QA phase dispatches. Convention unless yours differs."),
    SettingSpec("github_ref", "Workflow ref", "Delivery targets", section="engagement",
                placeholder="main", derived_from="code_index_ref"),
    SettingSpec("github_token", "GitHub token", "Credentials", section="credential", kind="secret",
                help="Needs actions:write to dispatch and actions:read to fetch results."),
    SettingSpec("dispatch_timeout_seconds", "Dispatch timeout (s)", "Remote execution", type="int",
                help="How long a dispatched phase may run before the run is failed."),
    SettingSpec("reconciler_interval_seconds", "Reconciler interval (s)", "Remote execution",
                type="float"),
    SettingSpec("local_dispatch_duration_seconds", "Simulated job duration (s)",
                "Remote execution", type="float"),

    # --- implementation ---
    SettingSpec("implementation_agent", "Who writes the change", "Implementation",
                type="enum", options=("inline", "github-copilot"),
                help="inline is this platform's own agent, refused before its edits reach "
                     "a branch. github-copilot hands the work to the client's cloud agent, "
                     "which opens its own pull request — containment is then checked "
                     "against what it actually did, and a refusal leaves the branch."),
    SettingSpec("copilot_model", "Copilot model", "Implementation",
                help="Optional. Leave blank to use the repository's default."),
    SettingSpec("copilot_custom_agent", "Copilot custom agent", "Implementation",
                help="Optional identifier for a custom agent configured in the repository."),
    SettingSpec("source_control_adapter", "Change target", "Implementation", type="enum",
                options=("local", "github"),
                help="local writes a branch in a working copy and pushes nothing."),
    SettingSpec("target_repo", "Repository", "Delivery targets", section="engagement",
                placeholder="owner/name", derived_from="code_index_repo",
                help="Only when changes are proposed somewhere other than the repository "
                     "being indexed — a fork, or a mirror."),
    SettingSpec("target_ref", "Base branch", "Delivery targets", section="engagement",
                placeholder="main", derived_from="code_index_ref"),
    SettingSpec("target_working_copy", "Working copy", "Delivery targets", section="engagement",
                relevant_when=("source_control_adapter", "local"),
                help="The checkout the local change target writes a branch in."),
    SettingSpec("target_environment", "Deploy environment", "Delivery targets", section="engagement",
                placeholder="staging"),

    # --- context graph ---
    SettingSpec("code_intelligence_adapter", "Index source", "Context graph", type="enum",
                options=("github", "local"),
                help="Where the code graph is derived from."),
    SettingSpec("code_index_repo", "Repository to index", "Codebase", section="engagement",
                placeholder="owner/name", owned_by="operations",
                help="The engagement's repository. Everything else that names a "
                     "repository falls back to this one."),
    SettingSpec("code_index_ref", "Ref to index", "Codebase", section="engagement",
                placeholder="main", owned_by="operations",
                help="The repository's default branch, unless overridden."),
    SettingSpec("code_index_max_depth", "Module depth", "Codebase", section="engagement",
                type="int", advanced=True,
                help="A module is a directory collapsed to this many path segments. "
                     "Deeper means finer modules; measured at 4 for this codebase."),
    SettingSpec("code_index_local_root", "Local path", "Codebase", section="engagement",
                relevant_when=("code_intelligence_adapter", "local"),
                help="The directory indexed when the index source is a checkout."),

    # --- platform ---
    SettingSpec("database_url", "Database", "Platform", kind="static"),
    SettingSpec("web_origin", "Console origin", "Platform", kind="static"),

    # --- where the execution plane reads its copy of the graph ---
    SettingSpec("qa_export_path", "Graph export path", "Codebase", section="engagement",
                advanced=True,
                help="Where the generated graph is written for the execution plane, which "
                     "runs in client CI with no route to this database. A convention; "
                     "change it only if the pipeline reads from somewhere else."),
    SettingSpec("qa_export_scope", "Export scope", "Codebase", section="engagement",
                owned_by="operations",
                help="The subtree the execution plane tests, chosen when syncing. A QA "
                     "run testing the app should not be told a change reaches the "
                     "control plane."),
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
    # Derivation undone before re-validating: `base` already has its derived
    # fields filled in, and passing those through makes them look explicitly
    # set, so they are never recomputed against the override.
    return Settings(**{**undone(base), **applicable})


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


def describe(
    base: Settings, overrides: dict[str, Any], current: Settings | None = None
) -> list[dict[str, Any]]:
    """The settings as the console should render them.

    Secrets report presence only. Everything else reports its effective value
    and whether that came from an override or from the environment.

    `current` is what is actually in force — the environment, plus stored
    overrides, plus the active project's engagement record, plus whatever
    was derived from the repository. Passed in rather than recomputed here
    because this module knows nothing about projects, and reporting the
    pre-overlay value made the page show one repository while the platform
    used another.
    """
    current = current if current is not None else effective(base, overrides)
    out: list[dict[str, Any]] = []

    for spec in SPECS:
        entry: dict[str, Any] = {
            "key": spec.key,
            "label": spec.label,
            "group": spec.group,
            "section": spec.section,
            "kind": spec.kind,
            "type": spec.type,
            "options": list(spec.options),
            "help": spec.help,
            "placeholder": spec.placeholder,
            "overridden": spec.key in overrides and spec.kind == "mutable",
            "derived_from": spec.derived_from,
            "owned_by": spec.owned_by,
            "advanced": spec.advanced,
            # Evaluated here rather than in the console, so the rule lives
            # beside the setting it qualifies.
            "relevant": (
                not spec.relevant_when
                or str(getattr(current, spec.relevant_when[0], None)) == spec.relevant_when[1]
            ),
            "relevant_when": list(spec.relevant_when),
            # Currently taking its value from somewhere else rather than
            # being set. The distinction the console needs: an empty box is
            # a question, a derived value is an answer.
            "derived": spec.key in getattr(current, "derived_keys", frozenset()),
        }
        if spec.kind == "secret":
            entry["configured"] = bool(getattr(current, spec.key, None))
            entry["value"] = None
        else:
            entry["value"] = getattr(current, spec.key, None)
        out.append(entry)

    return out


def check(settings: Settings) -> list[str]:
    """Why this configuration cannot be built, if it cannot.

    Every adapter factory raises when its prerequisites are missing — a
    GitHub target with no token, a coding agent with no repository. That is
    right at construction time and wrong as a way to find out: a change saved
    through the console used to persist first and rebuild second, so an
    unbuildable choice was written to the database and then failed. The
    process could not restart, and the only way back was editing SQLite by
    hand, which is not a recovery path for a console.

    Called with the settings a change *would* produce, before anything is
    written.
    """
    from app.adapters.registry import build_adapters

    try:
        build_adapters(settings, graph=None)
    except Exception as exc:  # noqa: BLE001 - any construction failure is the answer
        return [str(exc)]
    return []
