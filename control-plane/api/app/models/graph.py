from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class GraphNode(Base, TimestampMixin):
    """Identity, never content.

    `projection` holds only the attributes the platform gates on. The
    requirement text stays in Jira, the code stays in the repository — this
    row is a stable name for the thing and a pointer back to where it lives,
    which is why it cannot drift from the client's system of record.
    """

    __tablename__ = "graph_nodes"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    type: Mapped[str] = mapped_column(String, index=True)
    system: Mapped[str] = mapped_column(String)
    external_id: Mapped[str] = mapped_column(String)
    projection: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class GraphEdge(Base, TimestampMixin):
    """A typed relationship, and the run that asserted it.

    Append-only. An edge is never edited or deleted; a later assertion
    supersedes it by stamping `superseded_at`. An audit trail that can be
    rewritten is not one.
    """

    __tablename__ = "graph_edges"
    __table_args__ = (
        UniqueConstraint("type", "src_id", "dst_id", "run_id", name="uq_edge_assertion"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    type: Mapped[str] = mapped_column(String, index=True)
    src_id: Mapped[str] = mapped_column(String, ForeignKey("graph_nodes.id"), index=True)
    dst_id: Mapped[str] = mapped_column(String, ForeignKey("graph_nodes.id"), index=True)

    # Provenance: which run asserted this, in which phase, under which gate.
    run_id: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    phase: Mapped[str | None] = mapped_column(String, nullable=True)
    attributes: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
