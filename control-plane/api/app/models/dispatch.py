from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPKMixin


class Dispatch(UUIDPKMixin, TimestampMixin, Base):
    """One remote execution of one phase of one run.

    The row is three things at once, which is why all three dispatch hazards
    have the same answer: the unique constraint is the idempotency guard that
    stops a resumed node firing a second job, `result_payload` + `applied_at`
    are the queue that survives a result arriving before the graph parks, and
    `deadline_at` is the ledger the watchdog reads.
    """

    __tablename__ = "dispatches"
    __table_args__ = (UniqueConstraint("run_id", "phase", name="uq_dispatch_run_phase"),)

    # String is explicit: without it SQLAlchemy infers the column type from
    # runs.id, which is a UUID, and every str run_id fails on insert.
    run_id: Mapped[str] = mapped_column(String, ForeignKey("runs.id"), index=True)
    phase: Mapped[str] = mapped_column(String)

    provider: Mapped[str] = mapped_column(String)
    correlation_id: Mapped[str] = mapped_column(String, index=True)
    external_id: Mapped[str | None] = mapped_column(String, nullable=True)
    external_url: Mapped[str | None] = mapped_column(String, nullable=True)

    # pending | succeeded | failed | timed_out
    state: Mapped[str] = mapped_column(String, default="pending", index=True)
    result_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    evidence_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    detail: Mapped[str | None] = mapped_column(String, nullable=True)

    deadline_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
