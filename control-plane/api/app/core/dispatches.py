"""Persistence for remote executions.

Internal control-plane state, like the `runs` table — not an integration
point with a client system, so it lives in core/ rather than ports/. It is
still injected rather than imported directly, for the same reason the audit
sink is: a node that can only be tested against a live database is a node
nobody tests.

`claim` is the load-bearing method. It is what stops a resumed node firing a
second remote job — LangGraph re-executes a node's coroutine from the top on
resume, so everything before `interrupt()` runs twice, and here that would
mean launching a second workflow.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.db import get_sessionmaker
from app.models.dispatch import Dispatch
from app.ports.work_dispatch import DispatchHandle, DispatchResult

RESOLVED_STATES = ("succeeded", "failed", "timed_out")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime) -> datetime:
    """SQLite returns naive datetimes even from a timezone=True column."""
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


@dataclass
class DispatchRecord:
    """Storage-independent view of a dispatch, so the reconciler and the
    nodes never touch the ORM directly."""

    id: str
    run_id: str
    phase: str
    provider: str
    correlation_id: str
    state: str
    created_at: datetime
    deadline_at: datetime
    external_id: str | None = None
    external_url: str | None = None
    result_payload: dict[str, Any] | None = None
    evidence_ref: str | None = None
    detail: str | None = None
    applied_at: datetime | None = None

    @property
    def is_overdue(self) -> bool:
        return _now() >= _aware(self.deadline_at)

    def to_handle(self) -> DispatchHandle:
        return DispatchHandle(
            provider=self.provider,
            correlation_id=self.correlation_id,
            external_id=self.external_id,
            external_url=self.external_url,
        )

    def to_resume_payload(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "payload": self.result_payload,
            "evidence_ref": self.evidence_ref,
            "detail": self.detail,
            "external_url": self.external_url,
        }


class DispatchStore(Protocol):
    async def get(self, run_id: str, phase: str) -> DispatchRecord | None: ...

    async def claim(
        self, run_id: str, phase: str, provider: str, timeout_seconds: int
    ) -> DispatchRecord | None: ...

    async def attach_external(
        self, dispatch_id: str, external_id: str | None, external_url: str | None
    ) -> None: ...

    async def resolve(self, dispatch_id: str, result: DispatchResult) -> None: ...

    async def mark_applied(self, dispatch_id: str) -> None: ...

    async def list_pending(self) -> list[DispatchRecord]: ...

    async def list_unapplied(self) -> list[DispatchRecord]: ...


def _to_record(row: Dispatch) -> DispatchRecord:
    return DispatchRecord(
        id=str(row.id),
        run_id=row.run_id,
        phase=row.phase,
        provider=row.provider,
        correlation_id=row.correlation_id,
        state=row.state,
        created_at=_aware(row.created_at),
        deadline_at=_aware(row.deadline_at),
        external_id=row.external_id,
        external_url=row.external_url,
        result_payload=row.result_payload,
        evidence_ref=row.evidence_ref,
        detail=row.detail,
        applied_at=row.applied_at,
    )


class SqlDispatchStore:
    async def get(self, run_id: str, phase: str) -> DispatchRecord | None:
        async with get_sessionmaker()() as session:
            result = await session.execute(
                select(Dispatch).where(Dispatch.run_id == run_id, Dispatch.phase == phase)
            )
            row = result.scalars().first()
        return _to_record(row) if row else None

    async def claim(
        self, run_id: str, phase: str, provider: str, timeout_seconds: int
    ) -> DispatchRecord | None:
        """Reserve the right to dispatch this phase of this run.

        Returns the new record, or None if one already exists — which means
        this is the resume pass and the caller must not trigger anything.
        The reservation is written *before* the job is triggered so the row,
        not the trigger call, is the mutex.
        """
        row = Dispatch(
            id=uuid.uuid4(),
            run_id=run_id,
            phase=phase,
            provider=provider,
            correlation_id=uuid.uuid4().hex,
            state="pending",
            deadline_at=_now() + timedelta(seconds=timeout_seconds),
        )
        async with get_sessionmaker()() as session:
            session.add(row)
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                return None
        return _to_record(row)

    async def attach_external(
        self, dispatch_id: str, external_id: str | None, external_url: str | None
    ) -> None:
        async with get_sessionmaker()() as session:
            row = await session.get(Dispatch, uuid.UUID(dispatch_id))
            if row is not None:
                row.external_id = external_id or row.external_id
                row.external_url = external_url or row.external_url
                await session.commit()

    async def resolve(self, dispatch_id: str, result: DispatchResult) -> None:
        async with get_sessionmaker()() as session:
            row = await session.get(Dispatch, uuid.UUID(dispatch_id))
            if row is None or row.state in RESOLVED_STATES:
                return
            row.state = result.state
            row.result_payload = result.payload
            row.evidence_ref = result.evidence_ref
            row.detail = result.detail
            row.external_id = result.external_id or row.external_id
            row.external_url = result.external_url or row.external_url
            await session.commit()

    async def mark_applied(self, dispatch_id: str) -> None:
        async with get_sessionmaker()() as session:
            row = await session.get(Dispatch, uuid.UUID(dispatch_id))
            if row is not None and row.applied_at is None:
                row.applied_at = _now()
                await session.commit()

    async def list_pending(self) -> list[DispatchRecord]:
        async with get_sessionmaker()() as session:
            result = await session.execute(select(Dispatch).where(Dispatch.state == "pending"))
            return [_to_record(r) for r in result.scalars().all()]

    async def list_unapplied(self) -> list[DispatchRecord]:
        """Resolved but not yet consumed by the graph. This is the queue that
        survives a result arriving before the thread has parked."""
        async with get_sessionmaker()() as session:
            result = await session.execute(
                select(Dispatch)
                .where(Dispatch.state.in_(RESOLVED_STATES), Dispatch.applied_at.is_(None))
                .order_by(Dispatch.created_at)
            )
            return [_to_record(r) for r in result.scalars().all()]
