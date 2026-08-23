"""Port: persist and expose the audit trail.

Demo adapter: SQLite table. Future: client SIEM/logging.
"""

from datetime import datetime
from typing import Any, Literal, Protocol

from pydantic import BaseModel


class AuditEntry(BaseModel):
    run_id: str
    node_name: str
    phase: Literal["before", "after"]
    input_summary: dict[str, Any]
    output_summary: dict[str, Any] | None = None
    confidence_score: float | None = None
    confirmed: bool = False
    human_decision: Literal["approved", "rejected"] | None = None
    timestamp: datetime


class AuditSink(Protocol):
    async def write(self, entry: AuditEntry) -> None: ...

    async def query(self, run_id: str) -> list[AuditEntry]: ...
