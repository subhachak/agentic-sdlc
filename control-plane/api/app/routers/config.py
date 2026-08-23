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
        "settings": settings_store.describe(get_settings(), overrides),
        "history": changes,
        "active": {
            "model_provider": settings.llm_provider_adapter,
            "execution_target": settings.work_dispatch_adapter,
            "index_source": settings.code_intelligence_adapter,
            "gates": "auto-approved" if settings.auto_approve_gates else "human",
        },
    }


@router.put("")
async def update_config(request: Request, body: ConfigUpdate) -> dict:
    try:
        cleaned = await settings_store.save(body.changes)
    except settings_store.ConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    from app.main import reload_runtime

    await reload_runtime(request.app)

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
