from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPKMixin


class Run(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "runs"

    # Which engagement this run belongs to. Recorded on the run rather than
    # inferred from whatever is active now, so the trail still says which
    # codebase a decision was made about after someone switches project.
    project: Mapped[str] = mapped_column(String, default="default", index=True)
    status: Mapped[str] = mapped_column(String, default="pending")
    raw_requirement_text: Mapped[str] = mapped_column(String, default="")
