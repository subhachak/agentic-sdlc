"""Configuration through the control plane.

Reading is unrestricted; secrets report presence only and never a value.
Writing persists an override, rebuilds the adapters so the change takes
effect without a restart, and records what changed in the audit trail.
"""

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.core import settings_store
from app.core.config import get_settings

router = APIRouter(prefix="/config", tags=["config"])


class ConfigUpdate(BaseModel):
    # A value of None clears the override and restores the environment default.
    changes: dict[str, Any]


@router.get("")
async def read_config(request: Request) -> dict:
    overrides = await settings_store.load_overrides()
    changes = await settings_store.history()
    settings = request.app.state.settings
    return {
        # The live settings, not the environment's: this page showed the
        # value before the active project was applied, so a repository set
        # for a project read as unset here.
        "settings": settings_store.describe(get_settings(), overrides, settings),
        "history": changes,
        # Set when a stored override could not be applied and the platform
        # started on its environment defaults instead. Surfaced here because
        # the console is where it has to be fixed.
        "problem": getattr(request.app.state, "config_problem", None),
        "active": {
            "model_provider": settings.llm_provider_adapter,
            "execution_target": settings.work_dispatch_adapter,
            "index_source": settings.code_intelligence_adapter,
            "gates": "auto-approved" if settings.auto_approve_gates else "human",
        },
    }


@router.post("/preflight")
async def preflight(request: Request, body: ConfigUpdate) -> dict:
    """Would this change work, without applying it?

    So the console can say "this needs a token" while someone is choosing,
    rather than after they have saved.
    """
    problems = await _problems_with(body.changes)
    return {"ok": not problems, "problems": problems}


async def _problems_with(changes: dict[str, Any]) -> list[str]:
    try:
        cleaned = settings_store.validate(changes)
    except settings_store.ConfigError as exc:
        return [str(exc)]

    overrides = {**await settings_store.load_overrides(), **cleaned}
    overrides = {k: v for k, v in overrides.items() if v is not None}
    try:
        proposed = settings_store.effective(get_settings(), overrides)
    except settings_store.ConfigError as exc:
        return [str(exc)]
    return settings_store.check(proposed)


@router.post("/check-agent")
async def check_agent(request: Request) -> dict:
    """Verify the configured implementation agent can actually be reached.

    An admin choosing a client's coding agent otherwise finds out whether it
    works when a run reaches the implementation phase, which is an expensive
    place to discover a missing scope.
    """
    settings = request.app.state.settings
    if settings.implementation_agent == "inline":
        return {
            "ok": True,
            "agent": "inline",
            "detail": "this platform writes the change itself; there is nothing to reach",
        }

    dispatcher = request.app.state.adapters.implementation_dispatch
    if dispatcher is None:
        return {
            "ok": False,
            "agent": settings.implementation_agent,
            "detail": "the agent is selected but no adapter was built for it",
        }

    prober = getattr(dispatcher, "check_access", None)
    if prober is None:
        return {
            "ok": False,
            "agent": settings.implementation_agent,
            "detail": "this adapter cannot be checked without starting work",
        }

    try:
        result = await prober()
    except Exception as exc:  # noqa: BLE001 - the answer is that it did not work
        return {"ok": False, "agent": settings.implementation_agent, "detail": str(exc)}
    return {"agent": settings.implementation_agent, **result}


@router.put("")
async def update_config(request: Request, body: ConfigUpdate) -> dict:
    # Checked before anything is written. Saving first and rebuilding second
    # is how a single console change left a deployment that would not start.
    problems = await _problems_with(body.changes)
    if problems:
        raise HTTPException(status_code=422, detail="; ".join(problems))

    try:
        cleaned = await settings_store.save(body.changes)
    except settings_store.ConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    from app.main import reload_runtime

    try:
        await reload_runtime(request.app)
    except Exception as exc:  # noqa: BLE001 - the check passed, so this is a surprise
        # Belt and braces. The preflight said it would build; if it did not,
        # the stored value is withdrawn rather than left to fail every
        # subsequent start.
        await settings_store.save({key: None for key in cleaned})
        await reload_runtime(request.app)
        raise HTTPException(
            status_code=500,
            detail=f"could not apply the change and it has been rolled back: {exc}",
        ) from exc

    active_runs = sum(
        1 for task in request.app.state.active_tasks.values() if not task.done()
    )
    return {
        "applied": cleaned,
        "active_runs": active_runs,
        "warning": (
            f"{active_runs} run(s) are mid-flight and were started under the previous "
            "configuration."
            if active_runs
            else None
        ),
    }
