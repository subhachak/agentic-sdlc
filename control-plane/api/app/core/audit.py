"""AuditLogger wraps the AuditSink adapter. Called by the Gate Controller
(core/gate_controller.py) and by the generic @audited node-wrapper below —
never scattered ad hoc through node code.
"""

import json
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from functools import wraps
from typing import Any

from pydantic import BaseModel

from app.core.confidence import score_placeholder
from app.ports.audit_sink import AuditEntry, AuditSink

NodeFn = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


def _safe(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {k: _safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe(v) for v in value]
    try:
        json.dumps(value)
        return value
    except TypeError:
        return str(value)


def summarize(state: dict[str, Any]) -> dict[str, Any]:
    return {k: _safe(v) for k, v in state.items()}


class AuditLogger:
    def __init__(self, sink: AuditSink):
        self._sink = sink

    async def has_written(self, run_id: str, node_name: str, phase: str) -> bool:
        entries = await self._sink.query(run_id)
        return any(e.node_name == node_name and e.phase == phase for e in entries)

    async def write_before(self, run_id: str, node_name: str, input_summary: dict[str, Any]) -> None:
        await self._sink.write(
            AuditEntry(
                run_id=run_id,
                node_name=node_name,
                phase="before",
                input_summary=input_summary,
                timestamp=datetime.now(timezone.utc),
            )
        )

    async def write_after(
        self,
        run_id: str,
        node_name: str,
        input_summary: dict[str, Any],
        output_summary: dict[str, Any],
        *,
        confidence_score: float | None = None,
        confirmed: bool = False,
        human_decision: str | None = None,
    ) -> None:
        await self._sink.write(
            AuditEntry(
                run_id=run_id,
                node_name=node_name,
                phase="after",
                input_summary=input_summary,
                output_summary=output_summary,
                confidence_score=confidence_score,
                confirmed=confirmed,
                human_decision=human_decision,
                timestamp=datetime.now(timezone.utc),
            )
        )


def audited(node_name: str, logger: AuditLogger) -> Callable[[NodeFn], NodeFn]:
    """Decorator for BUSINESS nodes only — fires exactly one before/after audit
    pair per logical execution, regardless of retries underneath (see
    core/reliability.py). Gate nodes do NOT use this: the Gate Controller
    writes its own audit entries directly, since a gate's "after" carries a
    human_decision this generic wrapper has no way to know.
    """

    def decorator(fn: NodeFn) -> NodeFn:
        @wraps(fn)
        async def wrapper(state: dict[str, Any]) -> dict[str, Any]:
            run_id = state["run_id"]
            input_summary = summarize(state)
            await logger.write_before(run_id, node_name, input_summary)
            update = await fn(state)
            confidence = score_placeholder(node_name)
            await logger.write_after(
                run_id,
                node_name,
                input_summary,
                summarize(update),
                confidence_score=confidence.score,
                confirmed=confidence.confirmed,
            )
            return update

        return wrapper

    return decorator
