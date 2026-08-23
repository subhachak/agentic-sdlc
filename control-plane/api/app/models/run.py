from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPKMixin


class Run(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "runs"

    status: Mapped[str] = mapped_column(String, default="pending")
    raw_requirement_text: Mapped[str] = mapped_column(String, default="")
