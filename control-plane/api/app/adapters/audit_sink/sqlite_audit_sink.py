import uuid

from sqlalchemy import select

from app.core.db import get_sessionmaker
from app.models.audit_log import AuditLog
from app.ports.audit_sink import AuditEntry


class SqliteAuditSink:
    """Demo-default AuditSink adapter: the audit_log SQLite table. Own
    short-lived AsyncSession per call, same app DB as the rest of the models.
    """

    async def write(self, entry: AuditEntry) -> None:
        async with get_sessionmaker()() as session:
            session.add(
                AuditLog(
                    run_id=uuid.UUID(entry.run_id),
                    node_name=entry.node_name,
                    phase=entry.phase,
                    input_summary=entry.input_summary,
                    output_summary=entry.output_summary,
                    confidence_score=entry.confidence_score,
                    confirmed=entry.confirmed,
                    human_decision=entry.human_decision,
                    created_at=entry.timestamp,
                )
            )
            await session.commit()

    async def query(self, run_id: str) -> list[AuditEntry]:
        async with get_sessionmaker()() as session:
            result = await session.execute(
                select(AuditLog).where(AuditLog.run_id == uuid.UUID(run_id)).order_by(AuditLog.created_at)
            )
            rows = result.scalars().all()
            return [
                AuditEntry(
                    run_id=str(row.run_id),
                    node_name=row.node_name,
                    phase=row.phase,  # type: ignore[arg-type]
                    input_summary=row.input_summary,
                    output_summary=row.output_summary,
                    confidence_score=row.confidence_score,
                    confirmed=row.confirmed,
                    human_decision=row.human_decision,  # type: ignore[arg-type]
                    timestamp=row.created_at,
                )
                for row in rows
            ]
